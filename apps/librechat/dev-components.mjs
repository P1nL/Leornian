import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import { clientRoot, workspaceRoot, loadPinnedClient, sourceOverlayPlugin } from './pinned-client.mjs';
import { createNativeServer } from './native-server.mjs';
import { createWorkbenchFixtures } from './workbench-fixtures.mjs';
import { workbenchFiles, workbenchImports, workbenchOverlayPaths, overlayWorkbenchSource } from './workbench-overlay.mjs';
import { findWorkbenchStory, workbenchStories } from './workbench-catalog.mjs';

export function workbenchBootstrap() {
  return `
(() => {
  const params = new URLSearchParams(location.search);
  if (!params.has('__workbench')) return;
  const story = params.get('component') || 'page', state = params.get('state') || 'default';
  const instance = params.get('__workbench');
  const scope = [story, state, instance].join('~');
  if (!/^[a-z0-9~-]{1,180}$/.test(scope)) throw new Error('Invalid component preview scope');
  window.__LEORNIAN_WORKBENCH__ = { story, state, instance };
  document.documentElement.dataset.leornianHost = 'native';
  localStorage.setItem('lang', JSON.stringify('zh-Hans'));
  localStorage.setItem('theme', params.get('theme') === 'dark' ? 'dark' : 'light');
  localStorage.setItem('color-theme', params.get('theme') === 'dark' ? 'dark' : 'light');
  localStorage.setItem('side:expanded', state === 'collapsed' ? 'false' : 'true');
  const scopedUrl = (input) => {
    const url = new URL(input, location.href);
    if (url.origin === location.origin && /^\\/(api|leornian|health|__leornian)(\\/|$)/.test(url.pathname)) {
      url.pathname = '/__fixtures/' + scope + url.pathname;
    }
    return url;
  };
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = scopedUrl(input instanceof Request ? input.url : input);
    return originalFetch(input instanceof Request ? new Request(url, input) : url, init);
  };
  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    return originalOpen.call(this, method, scopedUrl(url).href, ...rest);
  };
  for (const method of ['pushState', 'replaceState']) {
    const original = history[method].bind(history);
    history[method] = (data, unused, target) => {
      if (target != null) {
        const next = new URL(target, location.href);
        if (next.origin === location.origin) {
          for (const key of ['__workbench', 'component', 'state', 'theme']) next.searchParams.set(key, params.get(key) || '');
          target = next.pathname + next.search + next.hash;
        }
      }
      return original(data, unused, target);
    };
  }
  addEventListener('pagehide', () => navigator.sendBeacon('/__fixtures/' + scope + '/__close'));
})();
`;
}

export async function createComponentWorkbench({ port = 5183 } = {}) {
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid local component port.');
  const { vite, config } = await loadPinnedClient('serve');
  const sessions = new Map();
  const sources = new Set(workbenchStories.flatMap((story) => [...story.source, ...story.styles]));
  const apiFor = async (scope) => {
    if (!sessions.has(scope)) {
      const [id, state, instance] = scope.split('~'), story = findWorkbenchStory(id);
      if (story.id !== id || !story.states.some((item) => item.id === state)) throw new Error('Unknown component preview.');
      const fixture = createWorkbenchFixtures({ instance, story: id, state });
      const pending = createNativeServer({
        directory: clientRoot, backend: 'http://127.0.0.1:1',
        fetchBackend: fixture.fetchBackend, sessionCookieName: 'leornian_component_preview',
      }).then((api) => ({ fixture, api }));
      sessions.set(scope, pending);
    }
    return sessions.get(scope);
  };
  let server;
  const host = {
    name: 'leornian-component-workbench-host',
    transformIndexHtml: {
      order: 'pre',
      handler(html, context) {
        if (context.path === '/__components') return html;
        return html.replace('<head>', `<head><script>${workbenchBootstrap()}</script>`);
      },
    },
    configureServer(viteServer) {
      viteServer.middlewares.use(async (request, response, next) => {
        const url = new URL(request.url, 'http://127.0.0.1');
        if (url.pathname === '/__components/source') {
          const path = url.searchParams.get('path');
          if (!sources.has(path)) { response.writeHead(404); response.end(); return; }
          try {
            const source = await readFile(resolve(workspaceRoot, path), 'utf8');
            response.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' });
            response.end(source);
          } catch { response.writeHead(404); response.end('Source unavailable'); }
          return;
        }
        if (url.pathname === '/' && request.headers.accept?.includes('text/html')) {
          response.writeHead(302, { Location: '/__components' }); response.end(); return;
        }
        if (url.pathname === '/__components') {
          const html = await viteServer.transformIndexHtml('/__components', `<!doctype html>
<html lang="zh-Hans"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>组件工作台 · Leornian</title></head><body><div id="workbench-root"></div>
<script type="module" src="/src/leornian-native/ComponentWorkbench.tsx"></script></body></html>`);
          response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
          response.end(html); return;
        }
        const match = /^\/__fixtures\/([a-z0-9~-]{1,180})(\/.*)$/.exec(url.pathname);
        if (!match) {
          if (/^\/(api|leornian|oauth)(\/|$)/.test(url.pathname)) {
            response.writeHead(403, { 'Content-Type': 'application/json' });
            response.end(JSON.stringify({ code: 'component_scope_required' })); return;
          }
          return next();
        }
        try {
          if (match[2] === '/__close') {
            (await sessions.get(match[1]))?.fixture.close(); sessions.delete(match[1]);
            response.writeHead(204); response.end(); return;
          }
          const { api } = await apiFor(match[1]);
          request.url = match[2] + url.search;
          request.headers.cookie = 'leornian_component_preview=component-preview-session';
          api.emit('request', request, response);
        } catch (error) {
          response.writeHead(400, { 'Content-Type': 'application/json' });
          response.end(JSON.stringify({ code: 'invalid_component_preview', message: error.message }));
        }
      });
      viteServer.httpServer?.once('close', () => {
        for (const pending of sessions.values()) void pending.then(({ fixture }) => fixture.close());
        sessions.clear();
      });
    },
  };
  server = await vite.createServer({
    ...config, root: clientRoot, configFile: false, cacheDir: resolve(workspaceRoot, '.local/component-workbench/vite'),
    plugins: [host, sourceOverlayPlugin({
      name: 'leornian-workbench-source', paths: workbenchOverlayPaths, files: workbenchFiles,
      imports: workbenchImports, overlay: overlayWorkbenchSource,
    }), ...config.plugins],
    server: { ...config.server, host: '127.0.0.1', port, strictPort: true, proxy: {},
      fs: { allow: [workspaceRoot] }, open: false },
  });
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const server = await createComponentWorkbench({ port: Number(process.argv[2] ?? 5183) });
  await server.listen();
  console.log(`Leornian component workbench: http://127.0.0.1:${server.config.server.port}/__components`);
}
