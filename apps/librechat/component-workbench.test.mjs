import { test } from 'node:test';
import assert from 'node:assert/strict';
import { access } from 'node:fs/promises';
import { resolve } from 'node:path';
import vm from 'node:vm';
import { workbenchBootstrap } from './dev-components.mjs';
import { createWorkbenchFixtures } from './workbench-fixtures.mjs';
import { sampleIds } from './workbench-data.mjs';
import { workbenchGroups, workbenchStories } from './workbench-catalog.mjs';
import { clientRoot, sourceOverlayPlugin, workspaceRoot } from './pinned-client.mjs';
import { workbenchFiles, workbenchImports, workbenchOverlayPaths, overlayWorkbenchSource } from './workbench-overlay.mjs';

test('every component navigation entry has a readable source and a defined state', async () => {
  assert.equal(new Set(workbenchStories.map((item) => item.id)).size, workbenchStories.length);
  for (const group of workbenchGroups) assert(workbenchStories.some((item) => item.group === group.id), group.id);
  for (const story of workbenchStories) {
    assert(story.states.length, story.id);
    for (const file of [...story.source, ...story.styles]) await access(resolve(workspaceRoot, file));
  }
});

test('source edits invalidate both extracted modules and locally owned upstream components', () => {
  const plugin = sourceOverlayPlugin({ name: 'component-test', paths: workbenchOverlayPaths,
    files: workbenchFiles, imports: workbenchImports, overlay: overlayWorkbenchSource });
  for (const [actual, served] of [
    ['apps/librechat/LearningChrome.tsx', resolve(clientRoot, 'src/leornian-native/LearningChrome.tsx')],
    ['apps/librechat/ui/components/Chat/Header.tsx', resolve(clientRoot, 'src/components/Chat/Header.tsx')],
  ]) {
    const module = { id: served };
    const result = plugin.handleHotUpdate({
      file: resolve(workspaceRoot, actual),
      server: { moduleGraph: { getModulesByFile: (file) => {
        assert.equal(file, served.replaceAll('\\', '/')); return new Set([module]);
      } } },
    });
    assert.deepEqual(result, [module]);
  }
});

test('product source overlays remain active when loading a locally editable upstream file', async () => {
  const plugin = sourceOverlayPlugin({ name: 'component-test', paths: workbenchOverlayPaths,
    files: workbenchFiles, imports: workbenchImports, overlay: overlayWorkbenchSource });
  const watched = [];
  const output = await plugin.load.call({ addWatchFile: (file) => watched.push(file) },
    resolve(clientRoot, 'src/components/Chat/ChatView.tsx'));
  assert.match(output, /BaselineComposer/);
  assert.match(output, /NativeSync/);
  assert.match(output, /data-workbench-region="header"/);
  assert(watched.some((file) => file.replaceAll('\\', '/').endsWith('/ui/components/Chat/ChatView.tsx')));
});

test('sample actions update only their own preview instance and keep unsupported actions explicit', async () => {
  const first = createWorkbenchFixtures({ instance: 'first' }), second = createWorkbenchFixtures({ instance: 'second' });
  const call = (fixture, path, init) => fixture.fetchBackend(`http://127.0.0.1:1${path}`, init);
  await call(first, `/v1/goals/${sampleIds.goal}`, { method: 'PATCH', body: JSON.stringify({ title: '修改后的样例' }) });
  assert.equal((await (await call(first, '/v1/snapshot')).json()).goals[0].title, '修改后的样例');
  assert.equal((await (await call(second, '/v1/snapshot')).json()).goals[0].title, 'Python 基础学习');
  assert.notEqual(first.snapshot.actor.id, second.snapshot.actor.id);
  assert.deepEqual(await (await call(first, `/v2/conversations/${sampleIds.conversation}/learning-artifacts`)).json(), []);
  assert.equal((await call(first, '/v1/unknown-paid-operation', { method: 'POST', body: '{}' })).status, 404);
  first.close(); second.close();
});

test('model editing, review feedback and environment decisions work against local samples', async () => {
  const fixture = createWorkbenchFixtures({ instance: 'actions', state: 'presented' });
  const call = async (path, body) => {
    const response = await fixture.fetchBackend(`http://127.0.0.1:1${path}`,
      body ? { method: 'POST', body: JSON.stringify(body) } : {});
    assert.equal(response.status, 200, path); return response.json();
  };
  await call('/v1/model-profiles', { label: '修改后的模型', model: 'sample-updated' });
  assert.equal((await call('/v1/model-configuration')).profiles[0].label, '修改后的模型');
  await call('/v1/review-activities/sample-review/responses', { rating: 'good' });
  assert.equal((await call('/v1/review-activities'))[0].state, 'completed');
  await call('/v1/environment-demands/sample-environment/decisions', { decision: 'revoke' });
  assert.equal((await call('/v1/execution-environments')).demands[0].decision, 'revoke');
  fixture.close();
});

test('fetch, XHR and internal navigation retain the same sample scope', async () => {
  const calls = [], values = new Map();
  class XHR { open(...args) { calls.push(['xhr', ...args]); } }
  const location = new URL('http://127.0.0.1:5183/c/new?__workbench=sample&component=page&state=default&theme=light');
  const history = {
    pushState(...args) { calls.push(['navigation', ...args]); },
    replaceState(...args) { calls.push(['navigation', ...args]); },
  };
  const context = {
    location, history, URL, URLSearchParams, Request, XMLHttpRequest: XHR,
    document: { documentElement: { dataset: {} } },
    localStorage: { setItem(key, value) { values.set(key, value); } }, addEventListener() {},
    window: { fetch: async (...args) => { calls.push(['fetch', ...args]); return new Response('{}'); } },
  };
  vm.runInNewContext(workbenchBootstrap(), context);
  await context.window.fetch('/api/config');
  new XHR().open('POST', '/api/auth/refresh', true);
  history.pushState({}, '', '/c/another?node=loops');
  assert.equal(calls[0][1].pathname, '/__fixtures/page~default~sample/api/config');
  assert.equal(new URL(calls[1][2]).pathname, '/__fixtures/page~default~sample/api/auth/refresh');
  const next = new URL(calls[2][3], location);
  assert.equal(next.searchParams.get('__workbench'), 'sample');
  assert.equal(next.searchParams.get('node'), 'loops');
});
