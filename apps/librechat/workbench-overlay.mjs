import { connectedFiles, connectedImports, connectedOverlayPaths, overlayConnectedSource } from './connected-overlay.mjs';
import { previewModules } from './preview-overlay.mjs';

const workbench = 'virtual:leornian-component-workbench';
export const workbenchFiles = [...new Set([...connectedFiles, ...previewModules,
  'ComponentWorkbench.tsx', 'WorkbenchBridge.tsx', 'WorkbenchSpecimens.tsx',
  'workbench-catalog.mjs', 'workbench-data.mjs', 'editable-ui.mjs', 'workbench.css', 'workbench-surface.css'])];
export const workbenchImports = { ...connectedImports, [workbench]: 'WorkbenchBridge.tsx' };
export const workbenchOverlayPaths = [...connectedOverlayPaths, 'src/routes/Root.tsx'];

export function overlayWorkbenchSource(path, source) {
  if (path === 'src/routes/Root.tsx') {
    source = source.replaceAll('\r\n', '\n');
    if (source.split('<Outlet />').length !== 2) throw new Error('Pinned root outlet changed.');
    return `import WorkbenchBridge from '${workbench}';\n` + source
      .replace('<Outlet />', '<Outlet /><WorkbenchBridge />')
      .replace(/(<UnifiedSidebar\s[\s\S]*?\/>)/, '<div data-workbench-region="sidebar">$1</div>');
  }
  const result = overlayConnectedSource(path, source);
  if (path === 'src/App.jsx') return result.replace('<QueryDevtoolsGate />', '');
  if (path === 'src/components/Chat/ChatView.tsx') {
    return result.replace(/header=\{\s*(<Header[\s\S]*?\/>)\s*\}/,
      'header={<div data-workbench-region="header">$1</div>}');
  }
  return result;
}
