import { createServer } from 'node:http';
import { readFile, realpath, stat } from 'node:fs/promises';
import { extname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { demoFiles, demoMaterials, demoTranscripts, listDemoConversations } from './demo-data.mjs';

const source = new URL('../../.local/librechat-preview/dist/', import.meta.url);
const notice = '前端交互演示 · 尚未接入 Leornian。操作只保存在当前标签页；不调用模型、执行代码或安装环境。左侧选择学习场景，顶部菜单查看路线/复习/记录；请勿填写真实 API Key。';
const previewUser = {
  id: 'librechat-ui-preview',
  username: 'ui-preview',
  email: 'preview@localhost',
  name: '学习者（演示）',
  avatar: '/assets/favicon-32x32.png',
  role: 'USER',
  provider: 'ui-preview-only',
  createdAt: '2026-11-03T00:00:00.000Z',
  updatedAt: '2026-11-03T00:00:00.000Z',
};
const permissions = Object.fromEntries(
  [
    'PROMPTS', 'BOOKMARKS', 'MEMORIES', 'AGENTS', 'MULTI_CONVO', 'TEMPORARY_CHAT',
    'RUN_CODE', 'WEB_SEARCH', 'PEOPLE_PICKER', 'MARKETPLACE', 'FILE_SEARCH',
    'FILE_CITATIONS', 'MCP_SERVERS', 'REMOTE_AGENTS', 'SKILLS', 'SHARED_LINKS', 'SCHEDULES',
  ].map((type) => [type, Object.fromEntries(
    [
      'USE', 'CREATE', 'UPDATE', 'READ', 'READ_AUTHOR', 'SHARE', 'OPT_OUT',
      'VIEW_USERS', 'VIEW_GROUPS', 'VIEW_ROLES', 'SHARE_PUBLIC', 'CONFIGURE_OBO',
    ].map((permission) => [permission, false]),
  )]),
);
const startup = {
  appTitle: 'LibreChat · 学习演示（只读）',
  serverDomain: '',
  emailLoginEnabled: false,
  registrationEnabled: false,
  socialLoginEnabled: false,
  passwordResetEnabled: false,
  emailEnabled: false,
  allowEmailChange: false,
  allowAccountDeletion: false,
  sharedLinksEnabled: false,
  publicSharedLinksEnabled: false,
  showBirthdayIcon: false,
  helpAndFaqURL: '',
  customFooter: '只读演示数据 · 未连接模型、真实学习记录或执行环境。',
  projects: { enabled: false },
  balance: { enabled: false },
  transactions: { enabled: false },
  interface: {
    customWelcome: 'LibreChat',
    landingFooter: true,
    modelSelect: false,
    parameters: false,
    presets: false,
    prompts: false,
    bookmarks: false,
    memories: false,
    multiConvo: false,
    agents: false,
    temporaryChat: false,
    runCode: false,
    webSearch: false,
    fileSearch: false,
    fileCitations: false,
    mcpServers: { use: false },
    marketplace: { use: false },
    remoteAgents: { use: false },
    skills: false,
    sharedLinks: false,
    schedules: false,
    feedback: false,
    autoSubmitFromUrl: false,
    artifactUndocking: false,
  },
};
// These are display fixtures, not Leornian identities, receipts, or business APIs.
const reads = new Map([
  ['/api/config', startup],
  ['/api/user', previewUser],
  ['/api/roles/USER', { name: 'USER', permissions }],
  ['/api/banner', {
    bannerId: 'librechat-interaction-demo-v2',
    persistable: true,
    message: `<span class="local-preview-notice" title="${notice}" aria-label="${notice}">前端演示 · 未接业务/模型 · 不执行或安装</span>`,
  }],
  ['/health', 'UI preview only; no backend connected'],
  ['/api/endpoints', { openAI: { userProvide: false, modelDisplayLabel: '未接入模型' } }],
  ['/api/models', { openAI: [] }],
  ['/api/endpoints/token-config', {}],
  ['/api/keys', { expiresAt: '' }],
  ['/api/agents/chat/active', { activeJobIds: [] }],
  ['/api/agents/tools/web_search/auth', { authenticated: false }],
  ['/api/search/enable', true],
  ['/api/agents', { data: [], has_more: false, first_id: null, last_id: null }],
  ['/api/projects', { projects: [], nextCursor: null }],
  ['/api/files', demoFiles],
  ['/api/files/config', {
    endpoints: { default: { disabled: true }, openAI: { disabled: true } },
  }],
  ['/api/presets', []],
  ['/api/tags', []],
  ['/api/user/settings/favorites', []],
  ['/api/user/settings/favorites/tools', []],
  ['/api/user/settings/pinned-order', []],
  ['/api/user/settings/skills/active', {}],
  ['/api/files/speech/config/get', {
    speechToText: false,
    textToSpeech: false,
    conversationMode: false,
    sttExternal: false,
    ttsExternal: false,
  }],
]);
const mimeTypes = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.mp3': 'audio/mpeg',
  '.wasm': 'application/wasm',
};
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "connect-src 'self'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "media-src 'self' blob:",
  "worker-src 'self' blob:",
  "frame-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'none'",
].join('; ');
const readonlyScript = `
if (!localStorage.getItem('lang')) localStorage.setItem('lang', JSON.stringify('zh-Hans'));
document.documentElement.dataset.librechatPreview = 'readonly';
const notice = ${JSON.stringify(notice)};
function disableWrites() {
  document.querySelectorAll('textarea, input[type="file"], [data-testid="composer-surface"] button, form button[type="submit"], button[id^="edit-demo-"], button[data-testid$="generation-button"], button[aria-label="Regenerate"], button[aria-label="重新生成"], button[aria-label="重新產生"], button[aria-label="Open Fork Menu"]').forEach((input) => {
    if (input.closest('[data-learning-demo]')) return;
    if (!input.disabled) input.disabled = true;
    if (input.title !== notice) input.title = notice;
  });
}
document.addEventListener('submit', (event) => {
  event.preventDefault();
  event.stopImmediatePropagation();
}, true);
new MutationObserver(disableWrites).observe(document.documentElement, {
  childList: true, subtree: true, attributes: true, attributeFilter: ['disabled'],
});
disableWrites();
`;

function inside(root, path) {
  const part = relative(root, path);
  return part !== '..' && !part.startsWith(`..${sep}`) && !isAbsolute(part);
}

export async function createPreviewServer(directory = fileURLToPath(source)) {
  const root = await realpath(directory);
  const index = (await readFile(resolve(root, 'index.html'), 'utf8')).replace(
    '<head>',
    '<head><script src="/__preview/readonly.js"></script>' +
    '<style>.local-preview-notice{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:12px;line-height:1.5}</style>',
  );
  return createServer(async (request, response) => {
    response.setHeader('Content-Security-Policy', csp);
    response.setHeader('Cache-Control', 'no-store');
    response.setHeader('X-Content-Type-Options', 'nosniff');
    response.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
    const send = (status, body, type = 'application/json; charset=utf-8') => {
      response.writeHead(status, { 'Content-Type': type });
      response.end(request.method === 'HEAD' ? undefined : body);
    };
    const json = (status, body) => send(status, JSON.stringify(body));
    try {
      const url = new URL(request.url, 'http://127.0.0.1');
      const path = decodeURIComponent(url.pathname);
      // The upstream auth context needs an in-memory display session to render its shell.
      // This is never accepted by, or forwarded to, Leornian or an upstream backend.
      if (request.method === 'POST' && path === '/api/auth/refresh') {
        json(200, { token: 'ui-preview-only-not-a-business-credential', user: previewUser });
        return;
      }
      if (!['GET', 'HEAD'].includes(request.method)) {
        json(403, { error: 'UI_PREVIEW_READ_ONLY', message: notice });
        return;
      }
      if (path === '/api/convos') {
        json(200, listDemoConversations(url.searchParams));
        return;
      }
      const transcript = /^\/api\/(convos|messages)\/(demo-[a-z-]+)$/.exec(path);
      if (transcript && demoTranscripts.has(transcript[2])) {
        const example = demoTranscripts.get(transcript[2]);
        json(200, transcript[1] === 'convos' ? example.conversation : example.messages);
        return;
      }
      const share = /^\/api\/share\/link\/(demo-[a-z-]+)$/.exec(path);
      if (share && demoTranscripts.has(share[1])) {
        json(200, { shareId: null, success: true, conversationId: share[1], targetMessageId: null });
        return;
      }
      if (path === '/api/agents/tools/calls' &&
        demoTranscripts.has(url.searchParams.get('conversationId'))) {
        json(200, []);
        return;
      }
      const status = /^\/api\/agents\/chat\/status\/(demo-[a-z-]+)$/.exec(path);
      if (status && demoTranscripts.has(status[1])) {
        json(200, { active: false, generationProtocolVersion: 2 });
        return;
      }
      const material = /^\/__preview\/materials\/(demo-[a-z-]+)$/.exec(path);
      if (material && demoMaterials.has(material[1])) {
        send(200, demoMaterials.get(material[1]).text, 'text/plain; charset=utf-8');
        return;
      }
      if (reads.has(path)) {
        json(200, reads.get(path));
        return;
      }
      if (path === '/__preview/readonly.js') {
        send(200, readonlyScript, mimeTypes['.js']);
        return;
      }
      // A preview must not install a persistent service worker on this origin.
      if (path === '/registerSW.js') {
        send(200, '// Service worker registration is disabled for UI preview.', mimeTypes['.js']);
        return;
      }
      if (path === '/sw.js' || /^\/(api|oauth)(\/|$)/.test(path)) {
        json(404, { error: 'UI_PREVIEW_UNSUPPORTED' });
        return;
      }
      if (path === '/' || path === '/index.html' ||
        (!extname(path) && request.headers.accept?.includes('text/html'))) {
        send(200, index, mimeTypes['.html']);
        return;
      }
      const candidate = resolve(root, `.${path}`);
      if (!inside(root, candidate)) {
        json(404, { error: 'NOT_FOUND' });
        return;
      }
      const target = await realpath(candidate);
      if (!inside(root, target) || !(await stat(target)).isFile()) {
        json(404, { error: 'NOT_FOUND' });
        return;
      }
      send(200, await readFile(target), mimeTypes[extname(target)] ?? 'application/octet-stream');
    } catch (error) {
      if (error.code === 'ENOENT' || error.code === 'ENOTDIR') {
        json(404, { error: 'NOT_FOUND' });
      } else if (error instanceof URIError) {
        json(400, { error: 'INVALID_PATH' });
      } else {
        console.error('LibreChat UI preview request failed:', error.message);
        json(500, { error: 'UI_PREVIEW_ERROR' });
      }
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const port = Number(process.argv[2] ?? 5182);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('Expected a valid local port, default: 5182');
  }
  const server = await createPreviewServer();
  server.on('error', (error) => {
    console.error(`LibreChat UI preview could not start: ${error.message}`);
    process.exitCode = 1;
  });
  server.listen(port, '127.0.0.1', () => {
    console.log(`LibreChat learning demo: http://127.0.0.1:${port}/c/demo-python-learning`);
    console.log('Read-only static sample data. No Leornian/upstream backend or model connection.');
  });
}
