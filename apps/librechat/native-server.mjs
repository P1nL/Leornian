import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import { Readable } from 'node:stream';
import { readFile, realpath, stat, unlink } from 'node:fs/promises';
import { extname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { nativeReplyOutcome } from './native-reply-outcome.mjs';

const noParent = '00000000-0000-0000-0000-000000000000';
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.webp': 'image/webp', '.ico': 'image/x-icon', '.woff2': 'font/woff2',
  '.woff': 'font/woff', '.wasm': 'application/wasm', '.webmanifest': 'application/manifest+json' };
const csp = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; font-src 'self' data:; media-src 'self' blob:; worker-src 'self' blob:; frame-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'";
const inside = (root, target) => { const path = relative(root, target); return path !== '..' && !path.startsWith(`..${sep}`) && !isAbsolute(path); };
const tokenFrom = (request, cookieName) => {
  const cookie = request.headers.cookie?.split(';').map((part) => part.trim()).find((part) => part.startsWith(`${cookieName}=`));
  return cookie ? decodeURIComponent(cookie.slice(cookieName.length + 1)) : '';
};
const permissions = Object.fromEntries(['PROMPTS', 'BOOKMARKS', 'MEMORIES', 'AGENTS', 'MULTI_CONVO',
  'TEMPORARY_CHAT', 'RUN_CODE', 'WEB_SEARCH', 'PEOPLE_PICKER', 'MARKETPLACE', 'FILE_SEARCH',
  'FILE_CITATIONS', 'MCP_SERVERS', 'REMOTE_AGENTS', 'SKILLS', 'SHARED_LINKS', 'SCHEDULES'].map((type) =>
  [type, Object.fromEntries(['USE', 'CREATE', 'UPDATE', 'READ', 'READ_AUTHOR', 'SHARE', 'OPT_OUT',
    'VIEW_USERS', 'VIEW_GROUPS', 'VIEW_ROLES', 'SHARE_PUBLIC', 'CONFIGURE_OBO'].map((right) => [right, false]))]));
const config = {
  appTitle: 'Leornian', registrationEnabled: false, emailLoginEnabled: false, socialLoginEnabled: false,
  passwordResetEnabled: false, emailEnabled: false, sharedLinksEnabled: false, publicSharedLinksEnabled: false,
  showBirthdayIcon: false, customFooter: ' ',
  projects: { enabled: false }, balance: { enabled: false }, transactions: { enabled: false },
  interface: { customWelcome: 'Leornian', landingFooter: true, modelSelect: false, parameters: false,
    presets: false, prompts: false, bookmarks: false, memories: false, multiConvo: false, agents: false,
    temporaryChat: false, runCode: false, webSearch: false, fileSearch: false, fileCitations: false,
    mcpServers: { use: false }, marketplace: { use: false }, remoteAgents: { use: false },
    skills: false, sharedLinks: false, schedules: false, feedback: false, autoSubmitFromUrl: false },
};
const presentationReads = new Map([
  ['/api/config', config], ['/api/roles/USER', { name: 'USER', permissions }],
  ['/api/banner', null], ['/api/endpoints', { openAI: { userProvide: false, modelDisplayLabel: 'Leornian 原生 Tutor' } }],
  ['/api/models', { openAI: [] }], ['/api/endpoints/token-config', {}], ['/api/keys', { expiresAt: '' }],
  ['/api/agents/chat/active', { activeJobIds: [] }], ['/api/agents/tools/web_search/auth', { authenticated: false }],
  ['/api/search/enable', false], ['/api/agents', { data: [], has_more: false, first_id: null, last_id: null }],
  ['/api/projects', { projects: [], nextCursor: null }], ['/api/files', []],
  ['/api/files/config', { endpoints: { default: { disabled: true }, openAI: { disabled: true } } }],
  ['/api/presets', []], ['/api/tags', []], ['/api/user/settings/favorites', []],
  ['/api/user/settings/favorites/tools', []], ['/api/user/settings/pinned-order', []],
  ['/api/user/settings/skills/active', {}],
  ['/api/files/speech/config/get', { speechToText: false, textToSpeech: false, conversationMode: false, sttExternal: false, ttsExternal: false }],
]);

export function nativeConversation(snapshot, conversation) {
  const turns = snapshot.turns.find((page) => page.conversation_id === conversation.id)?.turns ?? [];
  const last = turns.at(-1);
  return { conversationId: conversation.id, user: snapshot.actor.id,
    title: snapshot.goals.find((goal) => goal.id === conversation.goal_id)?.title ?? '学习对话',
    endpoint: 'openAI', model: 'Leornian', createdAt: conversation.created_at,
    updatedAt: last?.completed_at ?? last?.created_at ?? conversation.created_at, isArchived: false };
}
export function nativeMessages(snapshot, conversationId, turns =
  snapshot.turns.find((page) => page.conversation_id === conversationId)?.turns ?? []) {
  let parentMessageId = noParent;
  return turns.filter((turn) => turn.purpose !== 'item_supply').flatMap((turn) => {
    const automatic = turn.teaching_intent_id != null;
    const user = { conversationId, messageId: `${turn.id}:user`, parentMessageId, isCreatedByUser: true,
      text: turn.user_text, sender: snapshot.actor.display_name, createdAt: turn.created_at,
      updatedAt: turn.created_at, endpoint: 'openAI', model: 'Leornian',
      leornianFocus: turn.context_focus, leornianPurpose: turn.purpose,
      ...(turn.teaching_branch_id ? { leornianBranchId: turn.teaching_branch_id } : {}) };
    if (!automatic) parentMessageId = user.messageId;
    const stages = (turn.stage_replies ?? []).map((reply) => {
      const message = { ...user, messageId: `${turn.id}:stage:${reply.id}`, parentMessageId,
        isCreatedByUser: false, text: reply.text, sender: 'Tutor',
        ...(reply.thinking_text || reply.thinking_steps?.length ? { content: [
          { type: 'think', think: reply.thinking_text ?? '', leornian_steps: reply.thinking_steps ?? [],
            leornian_key: `${snapshot.actor.id}:${turn.id}:stage:${reply.id}` },
          { type: 'text', text: reply.text },
        ] } : {}),
        createdAt: reply.created_at, updatedAt: reply.created_at };
      parentMessageId = message.messageId;
      return message;
    });
    const steps = turn.thinking_steps ?? [];
    const stepOnly = steps.length && !steps.some((step) => step.status === 'running') &&
      !snapshot.runs?.some((run) => run.turn_id === turn.id &&
        ['queued', 'running', 'blocked_unknown'].includes(run.status));
    const outcome = nativeReplyOutcome(snapshot, turn);
    if (!turn.assistant_text?.trim() && !stepOnly && !outcome) {
      return automatic ? stages : [user, ...stages];
    }
    const assistant = { ...user, messageId: `${turn.id}:assistant`, parentMessageId,
      isCreatedByUser: false, text: turn.assistant_text ?? '', sender: 'Tutor',
      ...(outcome ? { leornianOutcome: outcome } : {}),
      ...(turn.thinking_text || steps.length ? { content: [
        { type: 'think', think: turn.thinking_text ?? '', leornian_steps: steps,
          leornian_key: `${snapshot.actor.id}:${turn.id}` },
        { type: 'text', text: turn.assistant_text ?? '' },
      ] } : {}),
      createdAt: turn.completed_at ?? steps.at(-1)?.completed_at ?? turn.created_at,
      updatedAt: turn.completed_at ?? steps.at(-1)?.completed_at ?? turn.created_at };
    parentMessageId = assistant.messageId;
    return automatic ? [...stages, assistant] : [user, ...stages, assistant];
  });
}

export async function createNativeServer({
  directory = fileURLToPath(new URL('../../.local/librechat-native/dist/', import.meta.url)),
  backend = 'http://127.0.0.1:8088', fetchBackend = fetch,
  sessionCookieName = 'leornian_local_session',
  sessionRecoveryFile = '',
} = {}) {
  if (!/^[A-Za-z0-9_]{1,64}$/.test(sessionCookieName)) throw new Error('Invalid local session cookie name.');
  const cookieName = sessionCookieName;
  const base = new URL(backend);
  if (base.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(base.hostname) ||
    base.username || base.password || base.pathname !== '/' || base.search || base.hash) throw new Error('Native API must be an explicit local HTTP origin.');
  const root = await realpath(directory);
  const indexPath = await realpath(resolve(root, 'index.html'));
  if (!inside(root, indexPath)) throw new Error('Client entry must be inside frontend assets.');
  let recovery = null;
  if (sessionRecoveryFile) {
    try {
      const recoveryPath = await realpath(sessionRecoveryFile);
      if (inside(root, recoveryPath)) throw new Error('Recovery handoff must be outside frontend assets.');
      const saved = JSON.parse(await readFile(recoveryPath, 'utf8'));
      if (typeof saved.token !== 'string' || !saved.token ||
        typeof saved.actor_id !== 'string' || !Array.isArray(saved.previous_digests) ||
        !saved.previous_digests.every((digest) => /^[a-f0-9]{64}$/.test(digest)) ||
        !Number.isFinite(Date.parse(saved.handoff_expires_at))) {
        throw new Error('Invalid local session recovery handoff.');
      }
      if (Date.parse(saved.handoff_expires_at) > Date.now()) recovery = saved;
      else await unlink(sessionRecoveryFile);
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  let recoveryExpiry;
  const forgetRecovery = async () => {
    if (!recovery) return;
    recovery = null;
    clearTimeout(recoveryExpiry);
    await unlink(sessionRecoveryFile).catch((error) => { if (error.code !== 'ENOENT') throw error; });
  };
  if (recovery) {
    recoveryExpiry = setTimeout(() => {
      void forgetRecovery().catch(() => console.warn('Local session recovery file cleanup failed.'));
    }, Date.parse(recovery.handoff_expires_at) - Date.now());
    recoveryExpiry.unref();
  }
  const acknowledgeRecovery = async (token) => {
    if (recovery?.token === token) await forgetRecovery();
  };
  const canRecover = (token) => recovery && Date.parse(recovery.handoff_expires_at) > Date.now() &&
    (!token || recovery.previous_digests.includes(createHash('sha256').update(token).digest('hex')));
  const api = async (path, token, init = {}) => {
    const response = await fetchBackend(new URL(path, base), { ...init, headers: {
      ...init.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}),
    } });
    if (!response.ok) {
      const error = new Error('Local API request failed'); error.status = response.status; throw error;
    }
    return response.status === 204 ? null : response.json();
  };
  return createServer(async (request, response) => {
    response.setHeader('Content-Security-Policy', csp);
    response.setHeader('Cache-Control', 'no-store');
    response.setHeader('X-Content-Type-Options', 'nosniff');
    response.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
    const send = (status, body, type = 'application/json') => {
      response.writeHead(status, { 'Content-Type': type });
      response.end(request.method === 'HEAD' ? undefined : body);
    };
    const json = (status, body) => send(status, JSON.stringify(body));
    const setSessionCookie = (session) => {
      const seconds = Math.floor((Date.parse(session.expires_at) - Date.now()) / 1000);
      if (!Number.isFinite(seconds) || seconds <= 0) throw new Error('Invalid local session expiry.');
      response.setHeader('Set-Cookie', `${cookieName}=${encodeURIComponent(session.token)}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${Math.min(seconds, 604800)}`);
    };
    try {
      const url = new URL(request.url, 'http://127.0.0.1'), path = decodeURIComponent(url.pathname);
      if (!['127.0.0.1', 'localhost', '[::1]'].includes(new URL(`http://${request.headers.host}`).hostname)) {
        json(403, { code: 'host_not_allowed' }); return;
      }
      const token = tokenFrom(request, cookieName);
      if (request.headers.origin && request.headers.origin !== `http://${request.headers.host}`) {
        json(403, { code: 'origin_not_allowed' }); return;
      }
      if (path.startsWith('/leornian/')) {
        const target = path.slice('/leornian'.length);
        const destination = new URL(target + url.search, base);
        if (!/^\/v[12]\//.test(destination.pathname) || /%2f|%5c/i.test(request.url)) {
          json(404, { code: 'not_found' }); return;
        }
        const headers = {};
        for (const name of ['content-type', 'content-length', 'idempotency-key', 'last-event-id', 'accept']) {
          if (request.headers[name]) headers[name] = request.headers[name];
        }
        if (token) headers.authorization = `Bearer ${token}`;
        const upstream = await fetchBackend(destination, {
          method: request.method, headers, redirect: 'error',
          ...(!['GET', 'HEAD'].includes(request.method) ? { body: Readable.toWeb(request), duplex: 'half' } : {}),
        });
        if (upstream.ok) await acknowledgeRecovery(token);
        response.writeHead(upstream.status, {
          'Content-Type': upstream.headers.get('content-type') ?? 'application/json',
          ...(upstream.headers.get('content-disposition') ? { 'Content-Disposition': upstream.headers.get('content-disposition') } : {}),
        });
        if (upstream.body) {
          const stream = Readable.fromWeb(upstream.body);
          response.on('close', () => stream.destroy());
          stream.on('error', () => response.destroy());
          stream.pipe(response);
        } else response.end();
        return;
      }
      if (request.method === 'POST' && path === '/api/auth/local') {
        const chunks = []; let size = 0;
        for await (const chunk of request) {
          size += chunk.length;
          if (size > 4096) { json(413, { code: 'invalid_session_request' }); return; }
          chunks.push(chunk);
        }
        const body = JSON.parse(Buffer.concat(chunks).toString());
        let session;
        if (typeof body.token === 'string' && body.token) {
          session = await api('/v1/local-sessions/refresh', body.token, { method: 'POST' });
        } else {
          session = await api('/v1/local-sessions', '', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ display_name: body.display_name }),
          });
        }
        setSessionCookie(session);
        await acknowledgeRecovery(session.token);
        json(200, { actor: session.actor }); return;
      }
      if (request.method === 'POST' && path === '/api/auth/refresh') {
        let session;
        if (token) {
          try {
            session = await api('/v1/local-sessions/refresh', token, { method: 'POST' });
          } catch (error) { if (error.status !== 401 || !canRecover(token)) throw error; }
        }
        if (!session && canRecover(token)) {
          const handoff = recovery;
          session = await api('/v1/local-sessions/refresh', handoff.token, { method: 'POST' });
          if (session.actor.id !== handoff.actor_id) throw new Error('Recovery identity mismatch.');
        }
        if (!session) { json(401, { code: 'unauthorized' }); return; }
        setSessionCookie(session);
        // Keep the handoff until the browser proves it received the new HttpOnly cookie.
        await acknowledgeRecovery(token);
        json(200, { token: session.token, user: { id: session.actor.id, username: session.actor.id,
          name: session.actor.display_name, email: '', role: 'USER', provider: 'leornian-local' } });
        return;
      }
      if (request.method === 'POST' && path === '/api/auth/logout') {
        response.setHeader('Set-Cookie', `${cookieName}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0`);
        await forgetRecovery();
        if (token) await api('/v1/local-sessions/current', token, { method: 'DELETE' });
        json(200, { message: 'Local browser session closed; learning history retained.' }); return;
      }
      if (!['GET', 'HEAD'].includes(request.method)) {
        json(403, { code: 'upstream_business_disabled', message: 'Use Leornian public contracts.' }); return;
      }
      if (path === '/health') {
        const upstream = await fetchBackend(new URL('/health/ready', base), {
          method: request.method, redirect: 'error',
        });
        send(upstream.status, await upstream.text(),
          upstream.headers.get('content-type') ?? 'application/json');
        return;
      }
      if (presentationReads.has(path)) { json(200, presentationReads.get(path)); return; }
      if (path === '/__leornian/bootstrap.js') {
        send(200, "if (!localStorage.getItem('lang')) localStorage.setItem('lang', JSON.stringify('zh-Hans')); document.documentElement.dataset.leornianHost = 'native';", types['.js']);
        return;
      }
      if (path === '/api/user' || path === '/api/convos' || /^\/api\/(messages|convos)\/[a-f0-9-]+$/.test(path)) {
        if (!token) { json(401, { code: 'unauthorized' }); return; }
        const snapshot = await api('/v1/snapshot', token);
        await acknowledgeRecovery(token);
        if (path === '/api/user') {
          json(200, { id: snapshot.actor.id, username: snapshot.actor.id, name: snapshot.actor.display_name,
            email: '', role: 'USER', provider: 'leornian-local' }); return;
        }
        if (path === '/api/convos') {
          const visible = new Set(snapshot.goals.map((goal) => goal.id));
          const all = [...snapshot.conversations].reverse().filter((c) =>
            visible.has(c.goal_id) && !c.hidden_from_recents)
            .map((c) => nativeConversation(snapshot, c));
          const cursor = url.searchParams.get('cursor'), start = cursor ? all.findIndex((c) => c.conversationId === cursor) + 1 : 0;
          json(200, { conversations: all.slice(start, start + 25), nextCursor: all[start + 25] ? all[start + 24].conversationId : null }); return;
        }
        const id = path.split('/').at(-1), conversation = snapshot.conversations.find((c) => c.id === id);
        if (!conversation) { json(404, { code: 'not_found' }); return; }
        if (path.includes('/messages/')) {
          const turns = [];
          let before;
          for (;;) {
            const query = new URLSearchParams({ limit: '100', ...(before ? { before } : {}) });
            const page = await api(`/v1/conversations/${id}/history?${query}`, token);
            turns.push(...page);
            if (page.length < 100) break;
            before = page.at(-1).id;
          }
          json(200, nativeMessages(snapshot, id, turns.reverse()));
        } else json(200, nativeConversation(snapshot, conversation));
        return;
      }
      if (path === '/api/agents/tools/calls') { json(200, []); return; }
      if (/^\/api\/agents\/chat\/status\//.test(path)) { json(200, { active: false, generationProtocolVersion: 2 }); return; }
      if (path === '/registerSW.js') { send(200, '// No persistent service worker.', types['.js']); return; }
      if (path === '/sw.js' || /^\/(api|oauth)(\/|$)/.test(path)) { json(404, { code: 'not_supported' }); return; }
      if (path === '/' || path === '/index.html' || (!extname(path) && request.headers.accept?.includes('text/html'))) {
        const index = (await readFile(indexPath, 'utf8')).replace(
          '<head>', '<head><script src="/__leornian/bootstrap.js"></script>',
        );
        send(200, index, types['.html']); return;
      }
      const candidate = resolve(root, `.${path}`);
      if (!inside(root, candidate)) { json(404, { code: 'not_found' }); return; }
      const file = await realpath(candidate);
      if (!inside(root, file) || !(await stat(file)).isFile()) { json(404, { code: 'not_found' }); return; }
      send(200, await readFile(file), types[extname(file)] ?? 'application/octet-stream');
    } catch (error) {
      if (response.headersSent) { response.destroy(); return; }
      json(error.status ?? (['ENOENT', 'ENOTDIR'].includes(error.code) ? 404 : 503),
        { code: error.status === 401 ? 'unauthorized' : 'native_host_unavailable',
          message: '本机 API 或当前构建未就绪；没有自动升级数据库或重发业务请求。' });
    }
  });
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const port = Number(process.argv[2] ?? 5181);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid local port.');
  const server = await createNativeServer({ backend: process.env.LEORNIAN_API_URL ?? 'http://127.0.0.1:8088' });
  server.listen(port, '127.0.0.1', () => console.log(`Native Leornian client: http://127.0.0.1:${port}/c/new`));
}
