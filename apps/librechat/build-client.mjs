import { rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { clientRoot, loadPinnedClient, sourceOverlayPlugin } from './pinned-client.mjs';

export async function buildPinnedClient({ directory, paths, files, imports, overlay, name }) {
  const output = fileURLToPath(new URL(`../../.local/${directory}/dist/`, import.meta.url));
  const { vite, config } = await loadPinnedClient('build');
  await vite.build({
    ...config, root: clientRoot, configFile: false,
    plugins: [sourceOverlayPlugin({ paths, files, imports, overlay, name }), ...config.plugins],
    build: { ...config.build, outDir: output, emptyOutDir: false },
  });
  await rm(resolve(output, 'assets/silence.mp3'), { force: true });
  console.log(`Native Leornian frontend built at ${output}`);
}
