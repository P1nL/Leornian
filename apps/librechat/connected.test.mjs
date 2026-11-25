import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { connectedFiles, connectedOverlayPaths, overlayConnectedSource } from './connected-overlay.mjs';
import { nativeOverlayPaths, overlayNativeSource } from './native-overlay.mjs';
import { previewOverlayPaths, overlayPreviewSource } from './preview-overlay.mjs';
import { defaultMaterialScope, intakeKey, prepareLearning, readIntake, sendTeachingTurn } from './native-intake.mjs';

test('default frontend commands use the connected baseline and keep legacy commands explicit', async () => {
  const { scripts } = JSON.parse(await readFile(new URL('../../package.json', import.meta.url), 'utf8'));
  assert.equal(scripts.dev, 'pnpm librechat:connected');
  assert.equal(scripts.build, 'pnpm librechat:build-connected');
  assert.equal(scripts['desktop:web-dev'], 'pnpm --filter @leornian/desktop dev');
  assert.equal(scripts['desktop:build'], 'pnpm --filter @leornian/desktop build');
});

function intakeFixture() {
  const values = new Map(), calls = [];
  const storage = { getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
  const state = { snapshot: { actor: { id: 'actor' } }, pending: [] };
  const store = { getSnapshot: () => state,
    write: async (...args) => { calls.push(['write', ...args]); return { job_id: 'job' }; },
    refresh: async () => calls.push(['refresh']) };
  const request = async (path, options) => {
    calls.push(['request', path, options]);
    return path === '/v1/jobs/job' ? { status: 'succeeded', result_ref: 'goal' }
      : { id: 'conversation', goal_id: 'goal' };
  };
  return { storage, state, store, request, calls, pause: async () => {} };
}

test('connected overlays reuse the baseline chrome and original native artifacts without demo state', async () => {
  for (const path of connectedOverlayPaths) {
    const source = await readFile(new URL(`../../.local/upstream/LibreChat-f4154b6/client/${path}`, import.meta.url), 'utf8');
    assert.equal(typeof overlayConnectedSource(path, source), 'string', path);
  }
  assert(connectedFiles.includes('LearningChrome.tsx'));
  assert(!connectedFiles.includes('demo-state.mjs'));
  assert(!connectedFiles.includes('DemoChrome.tsx'));
  const path = 'src/components/Chat/ChatView.tsx';
  const source = await readFile(new URL(`../../.local/upstream/LibreChat-f4154b6/client/${path}`, import.meta.url), 'utf8');
  const connected = overlayConnectedSource(path, source);
  assert(connected.includes('<BaselineStart />'));
  assert(connected.includes('<BaselineComposer conversationId={conversationId} />'));
  assert(connected.includes('NativeSync'));
});

test('connected message extras mount once for both text-only and thinking-plus-text replies', async () => {
  const root = '../../.local/upstream/LibreChat-f4154b6/client/';
  const paths = [
    ['src/components/Chat/Messages/Content/MessageContent.tsx', 'message'],
    ['src/components/Messages/ContentRender.tsx', 'msg'],
  ];
  for (const [path, prop] of paths) {
    const source = await readFile(new URL(root + path, import.meta.url), 'utf8');
    const output = overlayConnectedSource(path, source);
    assert.match(output, /import NativeMessageExtras from 'virtual:leornian-native-message-extras'/);
    assert.equal(output.split(`<NativeMessageExtras message={${prop}} />`).length, 2, path);
    assert.doesNotMatch(output, /<NativeArtifacts/);
  }
  assert(connectedFiles.includes('NativeMessageExtras.tsx'));
});

test('message-operation contexts use native actions while the upstream transport stays disabled', async () => {
  const path = 'src/Providers/ChatContext.tsx';
  const source = await readFile(new URL(`../../.local/upstream/LibreChat-f4154b6/client/${path}`, import.meta.url), 'utf8');
  for (const overlay of [overlayNativeSource, overlayConnectedSource]) {
    const output = overlay(path, source);
    assert.match(output, /useNativeChatActions\(useUpstreamChatContext\(\)\)/);
    assert.match(output, /virtual:leornian-native-chat-actions/);
  }
  assert(connectedFiles.includes('NativeChatActions.ts'));
});

test('conversation deletion keeps native cache handling and dialog styles while using public contracts', async () => {
  const root = '../../.local/upstream/LibreChat-f4154b6/client/';
  const mutations = 'src/data-provider/mutations.ts';
  const dialog = 'src/components/Conversations/ConvoOptions/DeleteButton.tsx';
  for (const overlay of [overlayNativeSource, overlayConnectedSource]) {
    const output = overlay(mutations, await readFile(new URL(root + mutations, import.meta.url), 'utf8'));
    assert.match(output, /deleteNativeConversation\(payload\)/);
    assert.doesNotMatch(output, /dataService\.deleteConversation\(payload\)/);
    assert.match(output, /removeConvoFromAllQueries\(queryClient, vars\.conversationId\)/);
    const content = overlay(dialog, await readFile(new URL(root + dialog, import.meta.url), 'utf8'));
    assert.match(content, /error instanceof Error \? error\.message/);
    assert.match(content, /com_leornian_delete_recent_confirm/);
    assert.match(content, /className="w-11\/12 max-w-md"/);
    assert.match(content, /disabled=\{deleteMutation\.isLoading\}/);
  }
});

test('learning navigation is defined and runs in both sidebar branches with LF and Windows CRLF', async () => {
  const path = 'src/hooks/Nav/useUnifiedSidebarLinks.ts';
  const original = await readFile(new URL(`../../.local/upstream/LibreChat-f4154b6/client/${path}`, import.meta.url), 'utf8');
  const lf = original.replaceAll('\r\n', '\n');
  for (const source of [lf, lf.replaceAll('\n', '\r\n')]) {
    const output = overlayConnectedSource(path, source);
    const start = '  const links = useMemo(() => {';
    const offset = output.indexOf(start) + start.length;
    const body = output.slice(offset, output.indexOf('\n  }, [', offset)).replaceAll(': NavLink', '');
    const buildLinks = new Function('insightsFeatureEnabled', `
      const BaselineRoutes = () => null, BaselineQuestionBank = () => null, ConversationsSection = () => null;
      const MessagesSquare = () => null, BookOpen = () => null, Layers = () => null;
      const BarChart3 = () => null, sideNavLinks = [];
      const isInsightsRoute = false, isInsightsAccessLoading = false, insightsAccess = { access: true };
      const location = { pathname: '/c/new' }, navigate = () => {};
      ${body}
    `);
    assert.deepEqual(buildLinks(false).map((link) => link.id), ['conversations', 'learning', 'question-bank']);
    assert.deepEqual(buildLinks(true).map((link) => link.id), ['conversations', 'learning', 'question-bank', 'insights']);
  }
  assert.throws(() => overlayConnectedSource(path,
    lf.replace('    if (\n      !insightsFeatureEnabled', '    if (\n      !changedFeature')), /sidebar links changed/);
});

test('connected settings expose only working appearance controls and independent model usage', async () => {
  const path = 'src/components/Nav/Settings/registry.tsx';
  const source = await readFile(new URL(`../../.local/upstream/LibreChat-f4154b6/client/${path}`, import.meta.url), 'utf8');
  const settings = overlayConnectedSource(path, source);
  assert.deepEqual([...settings.matchAll(/\bid: '([^']+)'/g)].map((match) => match[1]), [
    'theme', 'language', 'uiScale', 'leornianModelConfiguration', 'leornianModelRoles',
  ]);
  assert.match(settings, /Component: NativeModelRoles/);
  assert.doesNotMatch(settings, /SettingsTabs\/(?:Account|Data|Speech)|DemoPreferences|DemoEnvironmentSettings|Billing|ProviderKeys/);
  assert.throws(() => overlayConnectedSource(path, source.replace('export const registry:', 'export const changed:')), /changed/);
});

test('settings keep appearance as fallback and add usage as a real standalone tab', async () => {
  const path = 'src/components/Nav/Settings/types.ts';
  const source = await readFile(new URL(`../../.local/upstream/LibreChat-f4154b6/client/${path}`, import.meta.url), 'utf8');
  const settings = overlayConnectedSource(path, source);
  const exported = settings.slice(settings.indexOf('export const TABS:'));
  assert.match(exported, /upstreamTabs\.filter\(\(tab\) => tab\.id === SettingsTabValues.GENERAL\)/);
  assert.match(exported, /id: 'leornianModels'/);
  assert.match(exported, /id: 'leornianModelRoles'/);
  assert.doesNotMatch(exported, /leornianExecution|SettingsTabValues\.(CHAT|SPEECH|DATA|ACCOUNT)/);
});

test('settings remove click rings and duplicate small captions without deleting keyboard focus', async () => {
  const root = '../../.local/upstream/LibreChat-f4154b6/client/';
  const path = 'src/components/Nav/Settings/Dialog.tsx';
  const dialog = overlayConnectedSource(path, await readFile(new URL(root + path, import.meta.url), 'utf8'));
  assert.match(dialog, /leornian-settings/);
  assert.doesNotMatch(dialog, /(?<!visible:)focus:ring-2/);
  assert.match(dialog, /focus-visible:ring-2/);
  const section = 'src/components/Nav/Settings/Section.tsx';
  assert.doesNotMatch(overlayConnectedSource(section, await readFile(new URL(root + section, import.meta.url), 'utf8')), /<h3|text-xs/);
  const content = 'src/components/Nav/Settings/Content.tsx';
  assert.doesNotMatch(overlayConnectedSource(content, await readFile(new URL(root + content, import.meta.url), 'utf8')), /text-xs/);
  const styles = await readFile(new URL('ccs-models.css', import.meta.url), 'utf8');
  assert.match(styles, /button, select\):focus-visible/);
  assert.match(styles, /\[role=tabpanel\]:focus \{ outline: none/);
});

test('all client variants remove the silent audio iframe and preserve the app', async () => {
  const path = 'src/App.jsx';
  const source = await readFile(new URL(`../../.local/upstream/LibreChat-f4154b6/client/${path}`, import.meta.url), 'utf8');
  for (const [paths, overlay] of [
    [connectedOverlayPaths, overlayConnectedSource],
    [nativeOverlayPaths, overlayNativeSource],
    [previewOverlayPaths, overlayPreviewSource],
  ]) {
    assert(paths.includes(path));
    const result = overlay(path, source);
    assert.doesNotMatch(result, /silence\.mp3|audio-silence/);
    assert.match(result, /<App \/>/);
    assert.match(result, /<WakeLockManager \/>/);
    assert.match(result, /<ScreenshotProvider>/);
    assert.throws(() => overlay(path, source.replace('assets/silence.mp3', 'assets/other.mp3')), /changed/);
  }
});

test('landing goal preparation preserves the complete motivation and resumes the original receipt', async () => {
  const fixture = intakeFixture(), input = 'Learn Python\n' + 'a'.repeat(200);
  const first = await prepareLearning(input, fixture);
  const second = await prepareLearning(input, fixture);
  assert.equal(first.conversation.id, 'conversation');
  assert.deepEqual(second, first);
  assert.equal(fixture.calls.filter(([kind]) => kind === 'write').length, 1);
  const body = fixture.calls.find(([kind]) => kind === 'write')[2];
  assert.equal(body.title.length, 120);
  assert.equal(body.motivation, input);
  assert.equal(fixture.calls.filter(([, path]) => path === '/v1/conversations').length, 1);
});

test('queued preparation is restored without submitting another goal', async () => {
  const fixture = intakeFixture();
  let queued = true;
  const original = fixture.request;
  fixture.request = async (...args) => queued ? { status: 'queued' } : original(...args);
  const first = await prepareLearning('Learn Python', fixture);
  assert.equal(first.status, 'waiting');
  assert.equal(readIntake(fixture.storage, 'actor').job_id, 'job');
  queued = false;
  assert.equal((await prepareLearning('Learn Python', fixture)).conversation.id, 'conversation');
  assert.equal(fixture.calls.filter(([kind]) => kind === 'write').length, 1);
  assert.equal(readIntake(fixture.storage, 'another-actor'), null);
});

test('a queued attachment draft resumes its original goal before promoting the first real message', async () => {
  const fixture = intakeFixture(), original = fixture.request;
  let queued = true;
  fixture.request = async (...args) => args[0] === '/v1/jobs/job' && queued
    ? { status: 'queued' } : original(...args);
  const options = { ...fixture, materialScope: defaultMaterialScope };
  assert.equal((await prepareLearning('新学习计划', { ...options, attachmentDraft: true })).status, 'waiting');
  queued = false;
  const result = await prepareLearning('Learn Python using my uploaded textbook', options);
  assert.equal(result.conversation.id, 'conversation');
  assert.equal(fixture.calls.filter(([kind]) => kind === 'write').length, 1);
  const patch = fixture.calls.find(([kind, path, init]) =>
    kind === 'request' && path === '/v1/goals/goal' && init?.method === 'PATCH');
  assert.equal(JSON.parse(patch[2].body).motivation, 'Learn Python using my uploaded textbook');
  assert.equal(readIntake(fixture.storage, 'actor').attachment_draft, false);
});

test('an unknown goal result cannot be resent after refresh or changed input', async () => {
  const fixture = intakeFixture();
  let dispatches = 0;
  fixture.store.write = async () => {
    dispatches++;
    fixture.state.pending = [{ path: '/v1/goals', status: 'unknown' }];
    throw new Error('connection lost');
  };
  fixture.request = async () => { throw new Error('Receipt still unknown'); };
  await assert.rejects(prepareLearning('Learn Python', fixture), /connection lost/);
  await assert.rejects(prepareLearning('Learn Python', fixture), /Receipt still unknown/);
  await assert.rejects(prepareLearning('Learn SQL', fixture), /已提交/);
  assert.equal(dispatches, 1);
  assert.equal(readIntake(fixture.storage, 'actor').job_id, null);
});

test('a lost goal response recovers its exact job by GET and never repeats the original POST', async () => {
  const fixture = intakeFixture();
  const key = 'original-request';
  fixture.storage.setItem(intakeKey('actor'), JSON.stringify({
    actor_id: 'actor', text: 'Learn Python', request_key: key, job_id: null, conversation_id: null,
  }));
  const original = fixture.request;
  fixture.request = async (...args) => args[0] === `/v1/goal-requests/${key}` ? { job_id: 'job' } : original(...args);
  assert.equal((await prepareLearning('Learn Python', fixture)).conversation.id, 'conversation');
  assert.equal(fixture.calls.filter(([kind]) => kind === 'write').length, 0);
});

test('known failed jobs remain in history but release the landing form for a new explicit intent', async () => {
  const fixture = intakeFixture();
  fixture.request = async () => ({ status: 'failed', error_code: 'invalid_goal' });
  await assert.rejects(prepareLearning('Learn Python', fixture), /invalid_goal/);
  assert.equal(fixture.storage.getItem(intakeKey('actor')), null);
});

test('a completed unsent legacy intake preserves its question without blocking a different goal', async () => {
  const fixture = intakeFixture();
  fixture.storage.setItem(intakeKey('actor'), JSON.stringify({
    actor_id: 'actor', text: 'Learn Python', request_key: 'completed-goal',
    job_id: 'old-job', conversation_id: 'old-conversation', goal_id: 'old-goal',
  }));
  await prepareLearning('Learn SQL', fixture);
  assert.equal(fixture.storage.getItem('leornian.native.composer:actor:old-conversation'), 'Learn Python');
  const writes = fixture.calls.filter(([kind]) => kind === 'write');
  assert.equal(writes.length, 1);
  assert.equal(writes[0][2].motivation, 'Learn SQL');
  assert.notEqual(writes[0][3].key, 'completed-goal');
});

test('explicit subject authorization is part of the original goal fingerprint and is not inferred from text', async () => {
  const fixture = intakeFixture();
  const materialScope = { contract: 'goal-material-scope.v1', language: 'SQL',
    language_version: null, framework: null, framework_version: null, authorized_official_sources: true };
  const input = 'Learn grouping and counting';
  const options = { ...fixture, materialScope };
  await prepareLearning(input, options);
  await prepareLearning(input, options);
  const writes = fixture.calls.filter(([kind]) => kind === 'write');
  assert.equal(writes.length, 1);
  assert.deepEqual(writes[0][2].material_scope, materialScope);
  await assert.rejects(prepareLearning(input, { ...options, materialScope: {
    ...materialScope, language_version: '3.46',
  } }), /已提交.*科目授权/);
  await assert.rejects(prepareLearning(input, fixture), /已提交.*科目授权/);
  assert.equal(fixture.calls.filter(([kind]) => kind === 'write').length, 1);
});

test('legacy original goal receipts keep an absent subject and cannot acquire new authorization on replay', async () => {
  const fixture = intakeFixture();
  fixture.storage.setItem(intakeKey('actor'), JSON.stringify({
    actor_id: 'actor', text: 'Learn SQL', request_key: 'old-key', job_id: 'job', conversation_id: null,
  }));
  await assert.rejects(prepareLearning('Learn SQL', { ...fixture, materialScope: {
    language: 'SQL', authorized_official_sources: true,
  } }), /已提交.*科目授权/);
  assert.equal((await prepareLearning('Learn SQL', fixture)).conversation.id, 'conversation');
  assert.equal(fixture.calls.filter(([kind]) => kind === 'write').length, 0);
});

test('new public-material defaults preserve an already submitted official-only authorization', async () => {
  const fixture = intakeFixture();
  const original = { ...defaultMaterialScope };
  delete original.authorized_public_sources;
  await prepareLearning('Learn Java', { ...fixture, materialScope: original });
  await prepareLearning('Learn Java', { ...fixture, materialScope: defaultMaterialScope });
  const writes = fixture.calls.filter(([kind]) => kind === 'write');
  assert.equal(writes.length, 1);
  assert.deepEqual(writes[0][2].material_scope, original);
});

test('both hosts submit the same closed capabilities, exact session revision and receipt lookup', async () => {
  let sent;
  await sendTeachingTurn({ write: async (...args) => { sent = args; } }, 'conversation', 'Question',
    { kind: 'node', node_key: 'N1', expected_plan_revision: 3 }, { revision: 8 });
  const [path, body, options] = sent;
  assert.equal(path, '/v1/conversations/conversation/turns');
  assert.equal(body.teaching_session_revision, 8);
  assert.equal(body.focus.expected_plan_revision, 3);
  assert.equal(body.presentation_capabilities.actions.length, 9);
  assert.ok(body.presentation_capabilities.actions.includes('learning_example_runs.v2'));
  assert.ok(body.presentation_capabilities.actions.includes('learning_templates.v1'));
  assert.equal(options.lookup, `/v1/conversations/conversation/turn-requests/${options.key}`);
});
