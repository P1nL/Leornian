export function materialFileFormat(name) {
  const extension = name.split('.').pop()?.toLowerCase();
  return ({ txt: 'text', md: 'markdown', markdown: 'markdown', html: 'html', htm: 'html',
    pdf: 'pdf', docx: 'docx', png: 'png', jpg: 'jpeg', jpeg: 'jpeg' })[extension] ?? null;
}

export function materialFileIssue(file) {
  if (!file || !materialFileFormat(file.name)) return '请选择 PDF、DOCX、TXT、Markdown、HTML 或图片文件。';
  if (!file.size) return '文件为空，请选择有正文的材料。';
  if (file.size > 20_000_000) return '文件超过 20 MB，请按章节拆分。';
  return '';
}

export function materialCommandLookup(journal) {
  if (journal.stage === 'demand_unknown') return `/v1/material-demands/commands/${journal.keys.demand}`;
  if (journal.stage === 'upload_unknown') return `/v1/material-demands/${journal.demand.id}/uploads/commands/${journal.keys.upload}`;
  if (journal.stage === 'job_unknown') return `/v1/material-demands/${journal.demand.id}/files/commands/${journal.keys.job}`;
  if (journal.stage === 'bytes_unknown') return `/v1/material-uploads/${journal.upload.id}`;
  return null;
}

export const materialProgress = (job) => job.background_deferred
  ? job.state === 'blocked_unknown' ? '原处理结果未知，已暂停自动处理' : '不在本轮获取范围，已暂停自动处理'
  : ({
  queued: '等待后台处理', parsing: '正在提取原文', processing: '正在处理材料',
  waiting_dependency: '等待处理依赖', waiting_config: '等待本人模型配置',
  blocked_unknown: '原处理结果未知，等待核对', ready: '材料已完成准备', cancelled: '已取消',
})[job.state] ?? job.state;

export async function newMaterialFileJournal(file, goalId) {
  const issue = materialFileIssue(file);
  if (issue) throw new Error(issue);
  const bytes = await file.arrayBuffer();
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map((value) => value.toString(16).padStart(2, '0')).join('');
  return {
    stage: 'demand_ready', filename: file.name, byteSize: bytes.byteLength, digest,
    keys: { demand: crypto.randomUUID(), upload: crypto.randomUUID(), job: crypto.randomUUID() },
    material: {
      goal_id: goalId, title: file.name.slice(0, 160), format: materialFileFormat(file.name),
      authorized_use: true,
      purposes: ['reference', 'indexing', 'planning', 'lesson', 'teaching', 'item_author', 'item_review'],
      use_until: null, retain_until: null,
    },
  };
}

export async function continueMaterialFileUpload(file, journal, {
  store, request, persist, progress = (_text) => {}, actorId,
}) {
  let current = journal;
  const save = (next) => {
    if (store.getSnapshot().snapshot?.actor.id !== actorId) throw new Error('学习身份已切换，原上传保留。');
    current = next; persist(current);
  };
  save(current);
  if (current.stage.endsWith('_unknown')) {
    const key = current.stage === 'demand_unknown' ? current.keys.demand
      : current.stage === 'upload_unknown' ? current.keys.upload : current.keys.job;
    const pending = store.getSnapshot().pending?.some((entry) => entry.key === key);
    const receipt = pending && current.stage !== 'bytes_unknown'
      ? await store.reconcile(key) : await request(materialCommandLookup(current));
    if (current.stage === 'bytes_unknown') {
      if (receipt.state !== 'stored') throw new Error('原文件上传结果尚待确认，请重新选择同一文件读取原状态。');
      save({ ...current, upload: receipt, stage: 'job_ready' });
    } else save({ ...current,
      ...(current.stage === 'demand_unknown' ? { demand: receipt, stage: 'upload_ready' }
        : current.stage === 'upload_unknown' ? { upload: receipt, stage: 'bytes_ready' }
          : { job: receipt, stage: 'done' }),
    });
  }
  if (current.stage === 'demand_ready') {
    progress('正在登记资料');
    save({ ...current, stage: 'demand_unknown' });
    const demand = await store.write('/v1/material-demands', {
      goal_id: current.material.goal_id, purpose: 'reference', scope_mode: 'whole_source', required_facets: [],
    }, { key: current.keys.demand, lookup: materialCommandLookup(current) });
    save({ ...current, demand, stage: 'upload_ready' });
  }
  if (current.stage === 'upload_ready') {
    save({ ...current, stage: 'upload_unknown' });
    const upload = await store.write(`/v1/material-demands/${current.demand.id}/uploads`, {
      expected_demand_revision: current.demand.revision, material: current.material,
      content_digest: current.digest, byte_size: current.byteSize,
    }, { key: current.keys.upload, lookup: materialCommandLookup(current) });
    save({ ...current, upload, stage: 'bytes_ready' });
  }
  if (current.stage === 'bytes_ready') {
    const bytes = await file.arrayBuffer();
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
      .map((value) => value.toString(16).padStart(2, '0')).join('');
    if (digest !== current.digest || bytes.byteLength !== current.byteSize) throw new Error('请选择同一原文件继续上传。');
    progress('正在上传');
    save({ ...current, stage: 'bytes_unknown' });
    const upload = await request(`/v1/material-uploads/${current.upload.id}/content`, {
      method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: bytes,
    });
    save({ ...current, upload, stage: 'job_ready' });
  }
  if (current.stage === 'job_ready') {
    progress('正在准备教材');
    save({ ...current, stage: 'job_unknown' });
    const job = await store.write(`/v1/material-demands/${current.demand.id}/files`, {
      expected_demand_revision: current.demand.revision, upload_id: current.upload.id,
    }, { key: current.keys.job, lookup: materialCommandLookup(current) });
    save({ ...current, job, stage: 'done' });
  }
  progress('已上传');
  return current;
}
