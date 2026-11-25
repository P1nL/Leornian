const prefix = 'src/components/Nav/Settings/';
export const connectedSettingsPaths = ['registry.tsx', 'types.ts', 'Dialog.tsx', 'Section.tsx', 'Content.tsx']
  .map((file) => prefix + file);

const registry = `import { SettingsTabValues } from 'librechat-data-provider';
import type { SettingEntry } from './types';
import { ThemeSetting, LangSetting } from './controls';
import UiScaleSelector from '../SettingsTabs/General/UiScaleSelector';
import NativeModels, { NativeModelRoles } from 'virtual:leornian-native-models';

export const registry: SettingEntry[] = [
  { id: 'theme', tab: SettingsTabValues.GENERAL, section: 'appearance',
    labelKey: 'com_nav_theme', keywords: ['主题', '外观'], Component: ThemeSetting },
  { id: 'language', tab: SettingsTabValues.GENERAL, section: 'appearance',
    labelKey: 'com_nav_language', keywords: ['语言'], Component: LangSetting },
  { id: 'uiScale', tab: SettingsTabValues.GENERAL, section: 'appearance',
    labelKey: 'com_nav_ui_scale', keywords: ['缩放'], Component: UiScaleSelector },
  { id: 'leornianModelConfiguration', tab: 'leornianModels', section: 'apiKeys',
    labelKey: 'com_leornian_model_configuration',
    keywords: ['教学', '路线', '材料', 'Key', 'DeepSeek', '千问', '自定义'],
    Component: NativeModels },
  { id: 'leornianModelRoles', tab: 'leornianModelRoles', section: 'apiKeys',
    labelKey: 'com_leornian_model_roles',
    keywords: ['用途', '教学', '规划', '材料', 'OCR', 'Embedding', 'Rerank'],
    Component: NativeModelRoles },
];
`;

function once(source, before, after) {
  if (source.split(before).length !== 2) throw new Error('Pinned connected settings changed.');
  return source.replace(before, after);
}

export function overlayConnectedSettings(path, source) {
  source = source.replaceAll('\r\n', '\n');
  if (path === prefix + 'registry.tsx') {
    once(source, 'export const registry: SettingEntry[] = [', '');
    return registry;
  }
  if (path === prefix + 'types.ts') {
    let result = once(source, 'export type SettingsTab =',
      "export type SettingsTab =\n  | 'leornianModels'\n  | 'leornianModelRoles'");
    result = once(result, 'export const TABS: TabMeta[] = [', 'const upstreamTabs: TabMeta[] = [');
    return result + `
export const TABS: TabMeta[] = [
  ...upstreamTabs.filter((tab) => tab.id === SettingsTabValues.GENERAL).map((tab) => ({
    ...tab, labelKey: 'com_leornian_appearance' as const,
    sections: tab.sections.filter((section) => section.id === 'appearance'),
  })),
  { id: 'leornianModels', labelKey: 'com_leornian_model_configuration',
    icon: createElement(GearIcon),
    sections: [{ id: 'apiKeys', labelKey: 'com_leornian_model_configuration' }] },
  { id: 'leornianModelRoles', labelKey: 'com_leornian_model_roles',
    icon: createElement(MessageSquare, { className: 'icon-sm', 'aria-hidden': true }),
    sections: [{ id: 'apiKeys', labelKey: 'com_leornian_model_roles' }] },
];
`;
  }
  if (path === prefix + 'Dialog.tsx') {
    return once(source, "'bg-surface-dialog border-border-light",
      "'leornian-settings bg-surface-dialog border-border-light")
      .replaceAll('focus:ring-border-xheavy', 'focus-visible:ring-border-xheavy')
      .replaceAll('focus:ring-2', 'focus-visible:ring-2');
  }
  if (path === prefix + 'Section.tsx') {
    return `import type { ReactNode } from 'react';
export default function Section({ heading, children }: { heading: string; children: ReactNode; icon?: ReactNode; danger?: boolean }) {
  return <section aria-label={heading} className="leornian-settings-section">{children}</section>;
}
`;
  }
  if (path === prefix + 'Content.tsx') {
    return once(source,
      `<div className="text-text-tertiary mb-1.5 text-xs">
                    {localize(tabMeta.labelKey)} ›{' '}
                    {sectionMeta ? localize(sectionMeta.labelKey) : label}
                  </div>`,
      `<h3 className="mb-3 text-sm font-medium">{label}</h3>`);
  }
  return null;
}
