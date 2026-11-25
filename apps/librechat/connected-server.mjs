import { fileURLToPath } from 'node:url';
import { createNativeServer } from './native-server.mjs';

const port = Number(process.argv[2] ?? 5180);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid local port.');
const server = await createNativeServer({
  backend: process.env.LEORNIAN_API_URL ?? 'http://127.0.0.1:8088',
  sessionRecoveryFile: process.env.LEORNIAN_LOCAL_SESSION_RECOVERY_FILE ?? '',
  directory: fileURLToPath(new URL('../../.local/librechat-connected/dist/', import.meta.url)),
});
server.listen(port, '127.0.0.1', () => console.log(`Leornian baseline connected client: http://127.0.0.1:${port}/c/new`));
