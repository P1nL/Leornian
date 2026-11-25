import { buildPinnedClient } from './build-client.mjs';
import { connectedFiles, connectedImports, connectedOverlayPaths, overlayConnectedSource } from './connected-overlay.mjs';

const directory = process.argv[2] ?? 'librechat-connected';
if (!/^[a-z][a-z0-9-]{0,63}$/.test(directory)) throw new Error('Build directory must be a local output name.');
await buildPinnedClient({
  directory, files: connectedFiles, imports: connectedImports,
  paths: connectedOverlayPaths, overlay: overlayConnectedSource, name: 'leornian-baseline-connected-host',
});
