import assert from 'node:assert/strict';
import { mkdtemp, readFile, rmdir, unlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, test } from 'node:test';
import { createPreviewServer } from './preview.mjs';
import { galleryPreviewImport, modelPreviewImport, overlayPreviewSource, previewModules } from './preview-overlay.mjs';

let server;
let origin;
let directory;

before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'leornian-librechat-preview-'));
  await writeFile(join(directory, 'index.html'), '<html><head></head><body>client</body></html>');
  await writeFile(join(directory, 'asset.js'), 'export const installed = true;');
  server = await createPreviewServer(directory);
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  origin = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  await new Promise((done) => server.close(done));
  await unlink(join(directory, 'index.html'));
  await unlink(join(directory, 'asset.js'));
  await rmdir(directory);
});

test('serves the built shell and SPA routes with explicit readonly controls', async () => {
  for (const path of ['/', '/index.html', '/c/new', '/c/demo-python-learning', '/__preview/artifacts']) {
    const response = await fetch(`${origin}${path}`, { headers: { Accept: 'text/html' } });
    assert.equal(response.status, 200);
    assert.match(await response.text(), /__preview\/readonly\.js/);
    assert.match(response.headers.get('content-security-policy'), /connect-src 'self'/);
  }
  const script = await fetch(`${origin}/__preview/readonly.js`);
  assert.match(await script.text(), /input\.disabled = true/);
});

test('display session and banner cannot be mistaken for a real user or connected model', async () => {
  const refresh = await fetch(`${origin}/api/auth/refresh`, { method: 'POST' });
  const session = await refresh.json();
  assert.equal(session.user.provider, 'ui-preview-only');
  assert.equal(session.token, 'ui-preview-only-not-a-business-credential');
  const models = await fetch(`${origin}/api/models`).then((response) => response.json());
  assert.deepEqual(models, { openAI: [] });
  const banner = await fetch(`${origin}/api/banner`).then((response) => response.json());
  assert.equal(banner.persistable, true);
  assert.match(banner.message, /尚未接入 Leornian/);
  const role = await fetch(`${origin}/api/roles/USER`).then((response) => response.json());
  assert.ok(Object.values(role.permissions).every(
    (permissions) => Object.values(permissions).every((allowed) => allowed === false),
  ));
});

test('rejects chat, uploads, execution, credentials, and preferences without consuming bodies', async () => {
  for (const [method, path] of [
    ['POST', '/api/ask/openAI'],
    ['POST', '/api/files'],
    ['POST', '/api/code/environments'],
    ['PUT', '/api/keys'],
    ['PATCH', '/api/user/preferences'],
    ['DELETE', '/api/convos'],
  ]) {
    const response = await fetch(`${origin}${path}`, { method, body: 'not-a-real-request' });
    assert.equal(response.status, 403);
    assert.equal((await response.json()).error, 'UI_PREVIEW_READ_ONLY');
  }
});

test('unknown APIs and missing assets are not disguised as successful empty results', async () => {
  for (const path of ['/api/not-implemented', '/oauth/openid', '/missing.js']) {
    const response = await fetch(`${origin}${path}`, { headers: { Accept: 'text/html' } });
    assert.equal(response.status, 404);
    assert.match(response.headers.get('content-type'), /application\/json/);
  }
});

test('serves local assets but never filesystem paths outside the build directory', async () => {
  const asset = await fetch(`${origin}/asset.js`);
  assert.equal(asset.status, 200);
  assert.equal(await asset.text(), await readFile(join(directory, 'asset.js'), 'utf8'));
  const escape = await fetch(`${origin}/..%2f..%2f.env`);
  assert.equal(escape.status, 404);
  const invalid = await fetch(`${origin}/%FF.js`);
  assert.equal(invalid.status, 400);
});

test('disables service worker registration and does not serve a worker', async () => {
  const register = await fetch(`${origin}/registerSW.js`);
  assert.equal(register.status, 200);
  assert.doesNotMatch(await register.text(), /serviceWorker\.register/);
  assert.equal((await fetch(`${origin}/sw.js`)).status, 404);
});

test('demo histories have scoped, stable parent chains and are explicitly not real results', async () => {
  const { conversations, nextCursor } = await fetch(`${origin}/api/convos`).then((response) => response.json());
  assert.equal(conversations.length, 7);
  assert.equal(nextCursor, null);
  for (const conversation of conversations) {
    assert.match(conversation.conversationId, /^demo-/);
    assert.match(conversation.title, /^演示/);
    assert.equal(conversation.user, 'librechat-ui-preview');
    const path = `/api/messages/${conversation.conversationId}?toolPreviews=true`;
    const messages = await fetch(`${origin}${path}`).then((response) => response.json());
    assert.equal(messages.length, conversation.conversationId === 'demo-knowledge-checks' ? 7 : 4);
    assert.deepEqual(messages, await fetch(`${origin}${path}`).then((response) => response.json()));
    assert.deepEqual(messages.map(({ messageId }) => messageId), conversation.messages);
    for (const [index, message] of messages.entries()) {
      assert.equal(message.conversationId, conversation.conversationId);
      assert.equal(message.parentMessageId, index === 0
        ? '00000000-0000-0000-0000-000000000000' : messages[index - 1].messageId);
      if (!message.isCreatedByUser) assert.match(message.text, /只读演示/);
    }
    const detail = await fetch(`${origin}/api/convos/${conversation.conversationId}`).then((response) => response.json());
    assert.deepEqual(detail, conversation);
  }
});

test('demo files are plain local samples, not processed material or an external download', async () => {
  const files = await fetch(`${origin}/api/files`).then((response) => response.json());
  assert.equal(files.length, 2);
  for (const file of files) {
    assert.match(file.file_id, /^demo-/);
    assert.match(file.filename, /演示/);
    assert.equal(file.embedded, false);
    const response = await fetch(`${origin}${file.filepath}`);
    assert.match(response.headers.get('content-type'), /^text\/plain/);
    const text = await response.text();
    assert.equal(Buffer.byteLength(text, 'utf8'), file.bytes);
    assert.match(text, /演示材料/);
  }
});

test('display list filters and missing or real-looking identities never leak into sample history', async () => {
  for (const query of ['isArchived=true', 'cursor=next-page', 'projectId=real-project', 'pinned=true']) {
    const list = await fetch(`${origin}/api/convos?${query}`).then((response) => response.json());
    assert.deepEqual(list, { conversations: [], nextCursor: null });
  }
  for (const path of ['/api/convos/real-conversation', '/api/messages/demo-missing', '/__preview/materials/demo-missing']) {
    assert.equal((await fetch(`${origin}${path}`)).status, 404);
  }
  const before = await fetch(`${origin}/api/messages/demo-python-learning`).then((response) => response.json());
  const write = await fetch(`${origin}/api/messages/demo-python-learning`, {
    method: 'POST', body: JSON.stringify({ text: 'must not be saved' }),
  });
  assert.equal(write.status, 403);
  assert.deepEqual(await fetch(`${origin}/api/messages/demo-python-learning`).then((response) => response.json()), before);
});

test('demo history metadata confirms there are no model jobs, tool calls, or public shares', async () => {
  const id = 'demo-python-learning';
  const status = await fetch(`${origin}/api/agents/chat/status/${id}`).then((response) => response.json());
  assert.deepEqual(status, { active: false, generationProtocolVersion: 2 });
  const calls = await fetch(`${origin}/api/agents/tools/calls?conversationId=${id}`).then((response) => response.json());
  assert.deepEqual(calls, []);
  const share = await fetch(`${origin}/api/share/link/${id}`).then((response) => response.json());
  assert.equal(share.shareId, null);
  for (const path of [
    '/api/share/link/real-conversation', '/api/agents/chat/status/demo-missing',
    '/api/agents/tools/calls?conversationId=real-conversation',
  ]) {
    assert.equal((await fetch(`${origin}${path}`)).status, 404);
  }
});

test('build overlay adds settings and a current-learning header without replacing existing containers', () => {
  const registry = 'export const registry: SettingEntry[] = [\n  existingSetting,\n];';
  const result = overlayPreviewSource('src/components/Nav/Settings/registry.tsx', registry);
  assert.ok(result.includes(modelPreviewImport));
  assert.match(result, /tab: 'leornianModels'/);
  assert.match(result, /existingSetting/);
  assert.equal(registry, 'export const registry: SettingEntry[] = [\n  existingSetting,\n];');
  const types = "import { MessageSquare, Info } from 'lucide-react';\nexport type SettingsTab =\n  | 'general';\nexport const TABS: TabMeta[] = [existingTab];";
  const tabs = overlayPreviewSource('src/components/Nav/Settings/types.ts', types);
  assert.match(tabs, /id: 'leornianModels'/);
  assert.match(tabs, /existingTab/);
  const header = overlayPreviewSource('src/components/Chat/Header.tsx',
    '{!readOnly && <ModelSelector startupConfig={startupConfig} />}\n<BackgroundTasksButton />\n<HeaderMenu />\n<ExportAndShareMenu />');
  assert.match(header, /aria-label="当前学习"/);
  assert.match(header, /conversation\?\.title/);
  assert.match(header, /<DemoTasks/);
  assert.match(header, /<DemoLearningMenu/);
  assert.doesNotMatch(header, /<ModelSelector/);
  assert.equal(overlayPreviewSource('src/unrelated.ts', 'keep original'), null);
});

test('settings overlay stops when a pinned source insertion point is absent or ambiguous', () => {
  const path = 'src/components/Nav/Settings/registry.tsx';
  assert.throws(() => overlayPreviewSource(path, 'changed source'), /source changed/);
  assert.throws(() => overlayPreviewSource(path,
    'export const registry: SettingEntry[] = [export const registry: SettingEntry[] = ['),
  /source changed/);
});

test('gallery route uses a build overlay and preserves the original chat route', () => {
  const source = [
    'const routes = [',
    '                {',
    "                  path: 'c/:conversationId?',",
    '                  element: <ChatRoute />,',
    '                },',
    '];',
  ].join('\n');
  const result = overlayPreviewSource('src/routes/index.tsx', source);
  assert.ok(result.includes(galleryPreviewImport));
  assert.match(result, /path: '__preview\/artifacts',\n\s+element: <ArtifactGallery \/>/);
  assert.match(result, /path: 'c\/:conversationId\?',\n\s+element: <ChatRoute \/>/);
  assert.ok(previewModules.includes('ArtifactGallery.tsx'));
  assert.ok(previewModules.includes('artifact-catalog.mjs'));
  for (const module of ['LearningComponents.tsx', 'ComponentGallery.tsx', 'component-catalog.mjs']) {
    assert.ok(previewModules.includes(module));
  }
  assert.throws(() => overlayPreviewSource('src/routes/index.tsx', 'changed routes'), /source changed/);
});

test('model settings translations preserve upstream labels and support native settings search', () => {
  for (const [locale, label] of [
    ['en', 'Model Configuration'], ['zh-Hans', '模型配置'], ['zh-Hant', '模型設定'],
  ]) {
    const translated = JSON.parse(overlayPreviewSource(
      `src/locales/${locale}/translation.json`, '{"existingLabel":"unchanged"}',
    ));
    assert.deepEqual(translated, {
      existingLabel: 'unchanged', com_leornian_model_configuration: label,
      com_leornian_local_execution: locale === 'en' ? 'Local Execution' : locale === 'zh-Hant' ? '本機執行' : '本机执行',
      com_leornian_learning_preferences: locale === 'en' ? 'Learning Preferences' : locale === 'zh-Hant' ? '學習方式與提醒' : '学习方式与提醒',
    });
  }
});

test('demo sidebar search covers message text, not only conversation titles', async () => {
  const response = await fetch(`${origin}/api/convos?search=${encodeURIComponent('return 和 print')}`).then((result) => result.json());
  assert.ok(response.conversations.some((conversation) => conversation.conversationId === 'demo-python-learning'));
  assert.equal(await fetch(`${origin}/api/search/enable`).then((result) => result.json()), true);
});
