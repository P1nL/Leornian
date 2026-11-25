import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const root = fileURLToPath(new URL('../../', import.meta.url));
const pinned = createRequire(resolve(root, '.local/upstream/LibreChat-f4154b6/client/package.json'));
const packageRoot = (name) => dirname(pinned.resolve(`${name}/package.json`));

export default {
  root,
  oxc: { jsx: { runtime: 'automatic' } },
  plugins: [{
    name: 'installed-pinned-component-dependencies',
    enforce: 'pre',
    resolveId(id, importer) {
      if (!importer?.replaceAll('\\', '/').includes('/apps/librechat/') ||
        id.startsWith('.') || id.startsWith('/') || id.startsWith('node:') || id === 'vitest') return;
      try { return pinned.resolve(id); } catch { return undefined; }
    },
  }],
  resolve: {
    alias: {
      '~': resolve(root, '.local/upstream/LibreChat-f4154b6/client/src'),
      react: packageRoot('react'),
      'react-dom': packageRoot('react-dom'),
      'framer-motion': packageRoot('framer-motion'),
      'lucide-react': packageRoot('lucide-react'),
      '@librechat/client': pinned.resolve('@librechat/client'),
      '@testing-library/react': pinned.resolve('@testing-library/react'),
    },
  },
  test: {
    environment: 'node',
    include: ['apps/librechat/*.test.tsx'],
    setupFiles: ['apps/librechat/test-setup.ts'],
  },
};
