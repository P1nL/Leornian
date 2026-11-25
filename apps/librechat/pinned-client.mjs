import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { editableUiPaths } from './editable-ui.mjs';

export const clientRoot = fileURLToPath(new URL('../../.local/upstream/LibreChat-f4154b6/client/', import.meta.url));
export const workspaceRoot = fileURLToPath(new URL('../../', import.meta.url));
const normalize = (path) => path.replaceAll('\\', '/');

export async function loadPinnedClient(command) {
  const pinned = createRequire(resolve(clientRoot, 'package.json'));
  const vite = await import(pathToFileURL(pinned.resolve('vite')).href);
  const loaded = await vite.loadConfigFromFile({ command, mode: command === 'serve' ? 'development' : 'production' },
    resolve(clientRoot, 'vite.config.ts'), clientRoot);
  if (!loaded) throw new Error('Pinned frontend build configuration unavailable.');
  return { vite, config: loaded.config };
}

/** Both builds and the component workbench resolve the same adapter sources. */
export function sourceOverlayPlugin({ paths, files, imports, overlay, name }) {
  const root = normalize(resolve(clientRoot, 'src/leornian-native'));
  const overlays = new Map(paths.map((path) => [normalize(resolve(clientRoot, path)), path]));
  const modules = new Map(files.map((file) => [`${root}/${file}`, fileURLToPath(new URL(file, import.meta.url))]));
  const editable = new Map(editableUiPaths.map((file) => [
    normalize(resolve(clientRoot, 'src', file)), fileURLToPath(new URL(`ui/${file}`, import.meta.url)),
  ]));
  const virtual = new Map(Object.entries(imports).map(([id, file]) => [id, `${root}/${file}`]));
  const applied = new Set();
  return {
    name, enforce: 'pre',
    resolveId(id, importer) {
      if (virtual.has(id)) return virtual.get(id);
      const served = normalize(resolve(clientRoot, `.${id}`));
      if (id.startsWith('/src/leornian-native/') && modules.has(served)) return served;
      if (modules.has(normalize(id))) return normalize(id);
      if (importer && normalize(importer).startsWith(`${root}/`) && id.startsWith('.')) {
        const requested = normalize(resolve(importer.split('?')[0], '..', id));
        return [...modules.keys()].find((path) =>
          path === requested || path === `${requested}.tsx` || path === `${requested}.ts`);
      }
    },
    async load(id) {
      const path = normalize(id.split('?')[0]);
      if (modules.has(path)) {
        this.addWatchFile(modules.get(path));
        return readFile(modules.get(path), 'utf8');
      }
      if (!overlays.has(path) && !editable.has(path)) return;
      const actual = editable.get(path) ?? path;
      this.addWatchFile(actual);
      const source = await readFile(actual, 'utf8');
      if (!overlays.has(path)) return source;
      applied.add(overlays.get(path));
      return overlay(overlays.get(path), source);
    },
    handleHotUpdate(context) {
      const changed = normalize(context.file);
      const mirrored = [...modules, ...editable].filter(([, actual]) => normalize(actual) === changed);
      if (!mirrored.length) return;
      return [...new Set(mirrored.flatMap(([id]) =>
        [...(context.server.moduleGraph.getModulesByFile(id) ?? [])]))];
    },
    async generateBundle() {
      if (applied.size !== overlays.size) throw new Error('Incomplete native frontend overlay.');
      for (const [fileName, sourceName] of [
        ['licenses/Phosphor.txt', 'PHOSPHOR-LICENSE.txt'],
        ['licenses/CC-Switch.txt', 'CCS-LICENSE.txt'],
      ]) this.emitFile({ type: 'asset', fileName,
        source: await readFile(new URL(sourceName, import.meta.url), 'utf8') });
    },
  };
}
