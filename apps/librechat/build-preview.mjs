import { readFile, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { modelPreviewImport, artifactsPreviewImport, chromePreviewImport, galleryPreviewImport, overlayPreviewSource, previewOverlayPaths, previewModules } from './preview-overlay.mjs';

const client = fileURLToPath(new URL('../../.local/upstream/LibreChat-f4154b6/client/', import.meta.url));
const output = fileURLToPath(new URL('../../.local/librechat-preview/dist/', import.meta.url));
const require = createRequire(resolve(client, 'package.json'));
const { build, loadConfigFromFile } = await import(pathToFileURL(require.resolve('vite')).href);
const loaded = await loadConfigFromFile(
  { command: 'build', mode: 'production' }, resolve(client, 'vite.config.ts'), client,
);
if (!loaded) throw new Error('Could not load the pinned frontend build configuration.');

const normalize = (path) => path.replaceAll('\\', '/');
const overlays = new Map(previewOverlayPaths.map((path) => [normalize(resolve(client, path)), path]));
const previewRoot = normalize(resolve(client, 'src/leornian-preview'));
const modules = new Map(previewModules.map((name) => [`${previewRoot}/${name}`, new URL(name, import.meta.url)]));
const virtual = new Map([
  [modelPreviewImport, `${previewRoot}/ModelConfigurationPreview.tsx`],
  [artifactsPreviewImport, `${previewRoot}/LearningArtifacts.tsx`],
  [chromePreviewImport, `${previewRoot}/DemoChrome.tsx`],
  [galleryPreviewImport, `${previewRoot}/ArtifactGallery.tsx`],
]);
const applied = new Set();

await build({
  ...loaded.config,
  root: client,
  configFile: false,
  plugins: [{
    name: 'leornian-isolated-frontend-interaction-demo',
    enforce: 'pre',
    resolveId(id, importer) {
      if (virtual.has(id)) return virtual.get(id);
      if (importer && normalize(importer).startsWith(`${previewRoot}/`) && id.startsWith('./')) {
        const name = id.slice(2);
        return [...modules.keys()].find((path) => path === `${previewRoot}/${name}` || path === `${previewRoot}/${name}.tsx`);
      }
    },
    async load(id) {
      const path = normalize(id.split('?')[0]);
      if (modules.has(path)) return readFile(modules.get(path), 'utf8');
      const overlay = overlays.get(path);
      if (!overlay) return null;
      const result = overlayPreviewSource(overlay, await readFile(path, 'utf8'));
      applied.add(overlay);
      return result;
    },
    async generateBundle() {
      if (applied.size !== overlays.size) {
        throw new Error('Frontend interaction overlays were not fully included; the preview build is incomplete.');
      }
      this.emitFile({ type: 'asset', fileName: 'licenses/Phosphor.txt',
        source: await readFile(new URL('PHOSPHOR-LICENSE.txt', import.meta.url), 'utf8') });
    },
  }, ...loaded.config.plugins],
  build: {
    ...loaded.config.build,
    outDir: output,
    // Keep previous build output during a build; no recursive cleanup of local files.
    emptyOutDir: false,
  },
});
await rm(resolve(output, 'assets/silence.mp3'), { force: true });
console.log(`Isolated frontend interaction demo built at ${output}`);
