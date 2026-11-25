import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
const root = fileURLToPath(new URL('../../', import.meta.url));
const pinned = createRequire(resolve(root, '.local/upstream/LibreChat-f4154b6/client/package.json'));
const ts = pinned('typescript');
const client = resolve(root, '.local/upstream/LibreChat-f4154b6/client');
const options = {
  noEmit: true, strict: true, skipLibCheck: true, allowJs: true, checkJs: false,
  jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler,
  target: ts.ScriptTarget.ES2022, resolveJsonModule: true, esModuleInterop: true, allowSyntheticDefaultImports: true,
  paths: {
    react: [pinned.resolve('@types/react/package.json').replace('package.json', 'index.d.ts')],
    'react/*': [resolve(dirname(pinned.resolve('@types/react/package.json')), '*')],
    '@leornian/api-contracts': [resolve(root, 'packages/api-contracts/src/generated.ts')],
    '~/*': [resolve(client, 'src/*')],
  },
};
const host = ts.createCompilerHost(options);
host.resolveModuleNames = (names, containingFile) => names.map((name) => {
  const found = ts.resolveModuleName(name, containingFile, options, host).resolvedModule;
  if (found) return found;
  return ts.resolveModuleName(name, resolve(client, '__native_type_context.ts'), options, host).resolvedModule;
});
const program = ts.createProgram(['LearningCompositionV2.tsx', 'NativeLearning.tsx', 'NativeMessageExtras.tsx', 'NativeChatActions.ts', 'NativeModels.tsx', 'BaselineLearning.tsx',
  'ComponentWorkbench.tsx', 'WorkbenchBridge.tsx', 'WorkbenchSpecimens.tsx']
  .map((name) => resolve(root, 'apps/librechat', name)), options, host);
// The pinned client keeps its own tsconfig; this checker owns only the adapter sources.
const pinnedRoot = client.replaceAll('\\', '/') + '/';
const diagnostics = ts.getPreEmitDiagnostics(program).filter((diagnostic) =>
  !diagnostic.file || !diagnostic.file.fileName.replaceAll('\\', '/').startsWith(pinnedRoot));
if (diagnostics.length) {
  console.error(ts.formatDiagnosticsWithColorAndContext(diagnostics, {
    getCurrentDirectory: () => root, getCanonicalFileName: (name) => name, getNewLine: () => '\n',
  }));
  process.exitCode = 1;
} else console.log('Native host and reusable composition TypeScript passed.');
