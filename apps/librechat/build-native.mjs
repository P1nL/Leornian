import { buildPinnedClient } from './build-client.mjs';
import { nativeFiles, nativeImports, nativeOverlayPaths, overlayNativeSource } from './native-overlay.mjs';

const directory = process.argv[2] ?? 'librechat-native';
if (!/^[a-z][a-z0-9-]{0,63}$/.test(directory)) throw new Error('Build directory must be a local output name.');
await buildPinnedClient({
  directory, files: nativeFiles, imports: nativeImports,
  paths: nativeOverlayPaths, overlay: overlayNativeSource, name: 'leornian-native-public-contract-host',
});
