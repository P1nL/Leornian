import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, explain, request } from "./api";
import type {
  ModelConfiguration, ModelConnection, ModelConnectionTest, ModelProfile, ModelProfileInput, Session,
} from "./api";

const chatRoles = [
  ["tutor.v1", "Tutor 教学"], ["planner.v1", "路线规划"], ["lesson.v1", "课时正文"],
  ["delivery_review.v1", "独立交付检查"], ["evaluation.v1", "作答讲评"],
  ["material_review.v1", "材料变更独立复核"],
  ["artifact.v1", "教学文档"], ["item_author.v1", "题目作者"], ["item_blind.v1", "独立盲解"],
  ["item_review.v1", "题目审核"], ["gate_relation.v1", "Gate 独立性"],
  ["transfer_relation.v1", "新情境关系"],
] as const;
const operationLabels = { chat: "教学 / 聊天", ocr: "OCR", embedding: "文本向量", rerank: "重排序" };
const presets = {
  custom: { protocol: "chat_completions", base: "", region: "custom", label: "兼容 Chat Completions" },
  customDashscope: { protocol: "dashscope", base: "", region: "custom", label: "自定义 DashScope / 工作空间地址" },
  beijing: { protocol: "dashscope", base: "https://dashscope.aliyuncs.com", region: "cn-beijing", label: "千问 · 北京" },
  singapore: { protocol: "dashscope", base: "https://dashscope-intl.aliyuncs.com", region: "singapore", label: "千问 · 新加坡" },
  virginia: { protocol: "dashscope", base: "https://dashscope-us.aliyuncs.com", region: "us-virginia", label: "千问 · 美国弗吉尼亚" },
} as const;
const testStates = {
  queued: "已接收，等待后台测试", dispatching: "调用中", succeeded: "固定协议样例通过",
  failed: "测试未通过", unknown: "结果未知，不会自动重发", cancelled: "配置或会话已失效，可能已有调用",
};
const testReasons: Record<string, string> = {
  provider_rejected: "提供方已明确拒绝请求，请核对模型、区域、凭据和账号状态。",
  invalid_probe_response: "返回内容、向量维度或固定样例识别不符合本次测试合同。",
  model_unavailable: "配置未启用或已变化，没有使用共享凭据代发。",
  external_result_unknown: "没有完整回执，不能当作零调用或自动重试。",
  configuration_or_session_changed: "配置或会话已变化；已发生的调用和回执仍保留。",
};

export function modelTestMetrics(result: ModelConnectionTest["result"]) {
  if (!result) return "用量与耗时未报告";
  const values: string[] = [];
  const elapsed = result.elapsed_seconds;
  if (typeof elapsed === "number" && Number.isFinite(elapsed) && elapsed >= 0) {
    values.push(`派发至回执 ${elapsed.toFixed(2)} 秒`);
  }
  const usage = result.usage;
  if (usage && typeof usage === "object" && !Array.isArray(usage)) {
    const total = (usage as Record<string, unknown>).total_tokens;
    if (typeof total === "number" && Number.isSafeInteger(total) && total >= 0) {
      values.push(`总 Token ${total}`);
    }
  }
  return values.length ? values.join(" · ") : "用量与耗时未报告";
}

export function initialProfile(connectionId = ""): ModelProfileInput {
  return {
    label: "", connection_id: connectionId, model: "", operation: "chat",
    enabled: false, allow_private_material: false,
    roles: chatRoles.map(([role]) => role), context_tokens: 0, max_output_tokens: 0,
    thinking: "", timeout_seconds: 300, embedding_dimensions: 1024,
  };
}

function settingsError(problem: unknown) {
  if (problem instanceof ApiError) {
    if (problem.code === "stale_version") return "模型配置已变化。请重新读取配置并打开最新版后再提交，当前输入不会覆盖新版本。";
    if (problem.code === "precondition_failed") return "请检查连接协议、区域、模型职责与启用状态；重排序当前需要 DashScope 协议。";
    if (problem.status === 422) return "请检查必填项、API 地址、通道容量、超时和至少一项模型职责。";
    return explain(problem);
  }
  return "连接中断，保存结果尚未确认。请刷新配置列表；不会自动重发模型测试。";
}

export function ModelSettingsPanel({ session, onUpdated }: {
  session: Session; onUpdated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [configuration, setConfiguration] = useState<ModelConfiguration | null>(null);
  const [tests, setTests] = useState<ModelConnectionTest[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [preset, setPreset] = useState<keyof typeof presets>("custom");
  const [label, setLabel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [region, setRegion] = useState("custom");
  const [local, setLocal] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [rotating, setRotating] = useState<ModelConnection | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [profile, setProfile] = useState<ModelProfileInput>(() => initialProfile());
  const [editingProfile, setEditingProfile] = useState<ModelProfile | null>(null);
  const [billableConsent, setBillableConsent] = useState(false);
  const generation = useRef(0);
  const activeTests = tests.some((test) => ["queued", "dispatching"].includes(test.status));
  const customProvider = preset === "custom" || preset === "customDashscope";

  async function refresh() {
    const current = ++generation.current;
    const [config, history] = await Promise.all([
      request<ModelConfiguration>("/v1/model-configuration", session.token),
      request<ModelConnectionTest[]>("/v1/model-connection-tests", session.token),
    ]);
    if (current !== generation.current) return;
    setConfiguration(config); setTests(history);
    setProfile((previous) => previous.connection_id ? previous
      : { ...previous, connection_id: config.connections.find((item) => !item.deleted)?.id ?? "" });
  }

  useEffect(() => {
    if (!open) return;
    void refresh().catch((problem) => setError(settingsError(problem)));
    return () => { generation.current++; };
    // The panel is keyed by actor in App; switching identity discards all secret form state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, session.token]);

  useEffect(() => {
    if (!open || !activeTests) return;
    const timer = window.setTimeout(() => {
      void request<ModelConnectionTest[]>("/v1/model-connection-tests", session.token)
        .then(setTests).catch(() => setError("暂时无法读取测试进度，请重新同步；调用结果尚未确认。"));
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [open, activeTests, tests, session.token]);

  useEffect(() => {
    if (rotating) document.getElementById("model-api-key")?.focus();
  }, [rotating]);

  useEffect(() => {
    if (editingProfile) document.getElementById("profile-name")?.focus();
  }, [editingProfile]);

  async function change(operation: () => Promise<unknown>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      await operation(); await refresh(); onUpdated(); setNotice(success);
    } catch (problem) { setError(settingsError(problem)); }
    finally { setBusy(false); }
  }

  async function saveConnection(event: FormEvent) {
    event.preventDefault();
    const secret = apiKey;
    setApiKey("");
    await change(async () => {
      if (rotating) {
        await request(`/v1/model-connections/${rotating.id}`, session.token, {
          method: "PATCH", body: JSON.stringify({
            expected_revision: rotating.revision, api_key: secret,
          }),
        });
        setRotating(null);
      } else {
        await request("/v1/model-connections", session.token, {
          method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify({
            label: label.trim(), protocol: presets[preset].protocol,
            base_url: customProvider ? baseUrl.trim() : presets[preset].base,
            region: customProvider ? region.trim() : presets[preset].region,
            local_endpoint: customProvider && local, enabled, api_key: secret,
          }),
        });
        setLabel("");
      }
    }, "连接已保存。API Key 不会回传，轮换不会重发已经发送或结果未知的旧调用。");
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    await change(async () => {
      const path = editingProfile ? `/v1/model-profiles/${editingProfile.id}` : "/v1/model-profiles";
      await request(path, session.token, {
        method: editingProfile ? "PATCH" : "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          ...profile, ...(editingProfile ? { expected_revision: editingProfile.revision } : {}),
        }),
      });
      setEditingProfile(null); setProfile(initialProfile(profile.connection_id));
    }, "职责映射已保存。新步骤使用明确版本；旧请求不会静默换用新配置。");
  }

  function editProfile(value: ModelProfile) {
    const { id: _id, revision: _revision, created_at: _createdAt, ...fields } = value;
    setProfile(fields); setEditingProfile(value); setError(""); setNotice("");
  }

  return <section className="model-settings" aria-labelledby="model-settings-heading">
    <div className="section-heading">
      <h2 id="model-settings-heading">模型与材料外发设置</h2>
      <button className="text-button" type="button" aria-expanded={open}
        aria-controls="model-settings-body" onClick={() => {
          setApiKey(""); setRotating(null); setOpen((value) => !value);
        }}>
        {open ? "收起模型设置" : "配置我的模型"}
      </button>
    </div>
    <p className="tutor-description">一份提供方凭据可以供本身份的多个模型职责使用。代码仍只在本机隔离环境执行。</p>
    {open && <div id="model-settings-body">
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}
      <button type="button" className="text-button" disabled={busy}
        onClick={() => void refresh().catch((problem) => setError(settingsError(problem)))}>重新读取配置与测试结果</button>
      {!configuration ? <p className="empty">正在读取当前身份的配置…</p> : <>
        <p className="model-status" role="status">
          {configuration.credential_storage === "available" ? "本机凭据保管可用。" : "本机凭据保管尚未就绪，不能保存 API Key。"}
          {configuration.configuration_scope === "development" && " 当前是显式开发通道模式，不是其他用户的默认配置。"}
        </p>
        <form className="model-form" onSubmit={(event) => void saveConnection(event)}>
          <h3>{rotating ? `轮换 ${rotating.label} 的凭据` : "添加提供方连接"}</h3>
          {!rotating && <>
            <label htmlFor="model-provider">提供方协议与区域</label>
            <select id="model-provider" value={preset} disabled={busy} onChange={(event) => {
              const value = event.target.value as keyof typeof presets;
              setPreset(value); setLocal(false);
              if (value === "customDashscope") setRegion("cn-beijing");
            }}>{Object.entries(presets).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}</select>
            <label htmlFor="model-connection-label">连接名称</label>
            <input id="model-connection-label" required maxLength={100} value={label} disabled={busy}
              onChange={(event) => setLabel(event.target.value)} />
            {customProvider ? <>
              <label htmlFor="model-base-url">API Base URL</label>
              <input id="model-base-url" type="url" required value={baseUrl} disabled={busy}
                placeholder="填写提供方的 API 基础地址" onChange={(event) => setBaseUrl(event.target.value)} />
              {preset === "customDashscope" && <p className="provenance">填写官方区域或工作空间根地址，不附加 /api/v1 或 /compatible-mode/v1。区域可填 cn-beijing、singapore、us-virginia 或 cn-hongkong，必须与域名匹配。</p>}
              <label htmlFor="model-region">账号 / 通道区域</label>
              <input id="model-region" required maxLength={80} value={region} disabled={busy}
                onChange={(event) => setRegion(event.target.value)} />
              <label className="model-check"><input type="checkbox" checked={local} disabled={busy}
                onChange={(event) => setLocal(event.target.checked)} />这是本机模型，仅允许明确的回环地址</label>
            </> : <p className="provenance">使用 {presets[preset].base}，凭据必须属于对应区域。</p>}
          </>}
          <label htmlFor="model-api-key">API Key · 仅写入，不回显</label>
          <input id="model-api-key" type="password" autoComplete="new-password" spellCheck={false}
            required maxLength={16384} value={apiKey} disabled={busy}
            onChange={(event) => setApiKey(event.target.value)} />
          {!rotating && <label className="model-check"><input type="checkbox" checked={enabled} disabled={busy}
            onChange={(event) => setEnabled(event.target.checked)} />启用此连接；调用按本人账号计费</label>}
          <div className="form-footer">
            <p>密钥只送往本机凭据入口，不写入浏览器持久存储，也不交给学习代码。连接地址变更请新建连接。</p>
            {rotating && <button type="button" className="text-button" disabled={busy}
              onClick={() => { setRotating(null); setApiKey(""); }}>取消轮换</button>}
            <button className="primary" disabled={busy || !apiKey || configuration.credential_storage !== "available"}>
              {busy ? "正在保存…" : rotating ? "保存新凭据" : "保存连接"}
            </button>
          </div>
        </form>
        <ul className="model-connection-list">{configuration.connections.map((connection) => <li key={connection.id}>
          <div className="goal-heading"><h3>{connection.label}</h3>
            <span className="saved-state">{connection.deleted ? "已删除密钥" : connection.enabled ? "已启用" : "已停用"} · 版本 {connection.revision}</span></div>
          <p className="provenance">{connection.base_url} · {connection.region} · 凭据版本 {connection.credential_version}</p>
          {!connection.deleted && <div className="model-actions">
            <button className="text-button" type="button" disabled={busy} onClick={() => void change(
              () => request(`/v1/model-connections/${connection.id}`, session.token, {
                method: "PATCH", body: JSON.stringify({ expected_revision: connection.revision, enabled: !connection.enabled }),
              }), "连接状态已保存。停用阻止新派发，已发生的调用事实保留。",
            )}>{connection.enabled ? "停用连接" : "启用连接"}</button>
            <button className="text-button" type="button" disabled={busy}
              onClick={() => { setRotating(connection); setApiKey(""); }}>轮换密钥</button>
            <button className="text-button" type="button" disabled={busy}
              onClick={() => setDeleting(connection.id)}>删除凭据</button>
          </div>}
          {deleting === connection.id && <div className="model-actions">
            <p>删除会撤销此连接的所有凭据版本，不删除历史调用。确认删除？</p>
            <button className="text-button" type="button" disabled={busy} onClick={() => void change(async () => {
              await request(`/v1/model-connections/${connection.id}`, session.token, {
                method: "DELETE", body: JSON.stringify({ expected_revision: connection.revision }),
              }); setDeleting(null);
            }, "凭据已删除，新调用被撤销；历史配置和回执仍保留。")}>确认删除凭据</button>
            <button className="text-button" type="button" disabled={busy} onClick={() => setDeleting(null)}>保留凭据</button>
          </div>}
        </li>)}</ul>
        <form className="model-form" onSubmit={(event) => void saveProfile(event)}>
          <h3>{editingProfile ? `编辑模型配置 · 版本 ${editingProfile.revision}` : "选择模型与职责"}</h3>
          <label htmlFor="profile-name">配置名称</label>
          <input id="profile-name" required maxLength={100} value={profile.label} disabled={busy}
            onChange={(event) => setProfile({ ...profile, label: event.target.value })} />
          <label htmlFor="profile-connection">复用提供方连接</label>
          <select id="profile-connection" required value={profile.connection_id} disabled={busy}
            onChange={(event) => setProfile({ ...profile, connection_id: event.target.value })}>
            <option value="">选择本身份的连接</option>
            {configuration.connections.filter((connection) => !connection.deleted).map((connection) =>
              <option value={connection.id} key={connection.id}>{connection.label} · {connection.enabled ? "启用" : "停用"}</option>)}
          </select>
          <div className="model-field-pair"><div>
            <label htmlFor="profile-operation">操作协议</label>
            <select id="profile-operation" value={profile.operation} disabled={busy} onChange={(event) => {
              const operation = event.target.value as ModelProfileInput["operation"];
              setProfile({ ...profile, operation, roles: operation === "chat" ? chatRoles.map(([role]) => role) : [operation], thinking: "" });
            }}>{Object.entries(operationLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select>
          </div><div>
            <label htmlFor="profile-model">模型标识</label>
            <input id="profile-model" required maxLength={200} value={profile.model} disabled={busy}
              onChange={(event) => setProfile({ ...profile, model: event.target.value })} />
          </div></div>
          {profile.operation === "chat" ? <>
            <fieldset className="model-role-options"><legend>使用此配置的职责</legend>
              {chatRoles.map(([role, name]) => <label className="model-check" key={role}>
                <input type="checkbox" disabled={busy} checked={profile.roles.includes(role)}
                  onChange={(event) => setProfile({ ...profile, roles: event.target.checked
                    ? [...profile.roles, role] : profile.roles.filter((value) => value !== role) })} />{name}</label>)}
            </fieldset>
            <div className="model-field-pair"><div>
              <label htmlFor="profile-context">真实通道上下文容量（token）</label>
              <input id="profile-context" type="number" required min={1} max={10000000}
                value={profile.context_tokens || ""} disabled={busy}
                onChange={(event) => setProfile({ ...profile, context_tokens: Number(event.target.value) })} />
            </div><div>
              <label htmlFor="profile-output">真实通道最大输出（token）</label>
              <input id="profile-output" type="number" required min={1} max={2000000}
                value={profile.max_output_tokens || ""} disabled={busy}
                onChange={(event) => setProfile({ ...profile, max_output_tokens: Number(event.target.value) })} />
            </div></div>
            <label htmlFor="profile-thinking">提供方思考协议</label>
            <select id="profile-thinking" value={profile.thinking} disabled={busy}
              onChange={(event) => setProfile({ ...profile, thinking: event.target.value as ModelProfileInput["thinking"] })}>
              <option value="">不发送扩展参数</option><option value="enabled">启用兼容的 thinking 参数</option>
              <option value="disabled">显式关闭兼容的 thinking 参数</option>
            </select>
          </> : <>
            <p className="provenance">可用固定样例验证专用协议，不发送思考或工具参数；正常材料处理与质量验收尚未全部接通。</p>
            {profile.operation === "embedding" && <>
              <label htmlFor="profile-dimensions">请求的向量维度</label>
              <input id="profile-dimensions" type="number" required min={1} max={16384}
                value={profile.embedding_dimensions ?? 1024} disabled={busy}
                onChange={(event) => setProfile({ ...profile, embedding_dimensions: Number(event.target.value) })} />
              <p className="provenance">按实际模型填写，显式测试会核对返回维度；不代表向量或检索质量已验收。</p>
            </>}
          </>}
          <label htmlFor="profile-timeout">单次调用总超时（秒）</label>
          <input id="profile-timeout" type="number" required min={10} max={1800}
            value={profile.timeout_seconds} disabled={busy}
            onChange={(event) => setProfile({ ...profile, timeout_seconds: Number(event.target.value) })} />
          <label className="model-check"><input type="checkbox" checked={profile.allow_private_material} disabled={busy}
            onChange={(event) => setProfile({ ...profile, allow_private_material: event.target.checked })} />
            允许将所选目标、教材和必要教学上下文发送至此提供方，由本人账号计费</label>
          <label className="model-check"><input type="checkbox" checked={profile.enabled} disabled={busy}
            onChange={(event) => setProfile({ ...profile, enabled: event.target.checked })} />启用此模型配置</label>
          <div className="form-footer"><p>保存会替换所选职责的映射，不改写旧请求。容量需按实际通道填写，不等于广告中的理论上限。</p>
            {editingProfile && <button className="text-button" type="button" disabled={busy}
              onClick={() => { setEditingProfile(null); setProfile(initialProfile(profile.connection_id)); }}>取消编辑</button>}
            <button className="primary" disabled={busy || !profile.connection_id || !profile.roles.length}>保存模型与职责</button>
          </div>
        </form>
        <label className="model-check"><input type="checkbox" checked={billableConsent} disabled={busy}
          onChange={(event) => setBillableConsent(event.target.checked)} />
          允许按所选模型发送一组固定样例：聊天消息、2 条向量/排序文本或一张小型 OCR 图片；可能计费，不发送教材，不证明教学或材料质量。</label>
        <ul className="model-profile-list">{configuration.profiles.map((value) => {
          const connection = configuration.connections.find((item) => item.id === value.connection_id);
          return <li key={value.id}>
            <h3>{value.label} · {value.model}</h3>
            <p className="provenance">{operationLabels[value.operation]} · 配置版本 {value.revision} · {value.enabled ? "已启用" : "已停用"}</p>
            <p className="provenance">当前职责：{configuration.mappings.filter((mapping) => mapping.profile_id === value.id)
              .map((mapping) => chatRoles.find(([role]) => role === mapping.role)?.[1] ?? mapping.role).join("、") || "无"}</p>
            <div className="model-actions">
              <button className="text-button" type="button" disabled={busy} onClick={() => editProfile(value)}>编辑此模型配置</button>
              {connection && !connection.deleted && <button className="text-button" type="button"
                disabled={busy || !billableConsent || !value.enabled || !connection.enabled}
                onClick={() => void change(async () => {
                  setBillableConsent(false);
                  await request(`/v1/model-connections/${connection.id}/tests`, session.token, {
                    method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
                    body: JSON.stringify({ expected_connection_revision: connection.revision, profile_id: value.id, allow_billable: true }),
                  });
                }, "测试已接收。刷新只读取原任务，不重新调用模型。")}>测试{operationLabels[value.operation]}连接（可能计费）</button>}
            </div>
          </li>;
        })}</ul>
        {tests.length > 0 && <div className="model-test-history"><h3>最近的显式测试</h3>
          <ul>{tests.map((test) => <li key={test.id}>
            <p>{testStates[test.status]} · {configuration.profiles.find((value) => value.id === test.profile_id)?.label ?? "历史配置"}</p>
            {test.error_code && testReasons[test.error_code] && <p>{testReasons[test.error_code]}</p>}
            {test.result && <small>{modelTestMetrics(test.result)}；此结果不代表材料处理、工具回合或教学质量验收。</small>}
          </li>)}</ul></div>}
      </>}
    </div>}
  </section>;
}
