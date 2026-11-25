// Adapted from CC Switch ProviderPresetSelector.tsx; see CCS-UPSTREAM.md.
import { useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Search, SlidersHorizontal, X } from 'lucide-react';

export interface PresetEntry {
  id: string;
  preset: {
    name: string;
    websiteUrl: string;
    detail: string;
    searchTerms: string[];
  };
}

interface ProviderPresetSelectorProps {
  selectedPresetId: string | null;
  presetEntries: PresetEntry[];
  onPresetChange: (value: string) => void;
  onChange: () => void;
  disabled?: boolean;
}

export function ProviderPresetSelector({
  selectedPresetId, presetEntries, onPresetChange, onChange, disabled,
}: ProviderPresetSelectorProps) {
  const entry = presetEntries.find((item) => item.id === selectedPresetId);
  if (!entry) {
    return <PresetPicker entries={presetEntries} onPick={onPresetChange} disabled={disabled} />;
  }
  return <PresetBar entry={entry} onChange={onChange} disabled={disabled} />;
}

function PresetIconBox({ preset }: { preset?: PresetEntry['preset'] }) {
  return <span aria-hidden="true" className="ccs-preset-icon">
    {preset ? preset.name.slice(0, 1).toUpperCase() : <SlidersHorizontal size={18} />}
  </span>;
}

function PresetBar({ entry, onChange, disabled }: {
  entry: PresetEntry; onChange: () => void; disabled?: boolean;
}) {
  const name = entry.preset.name;
  return <div data-preset-selector="" className="ccs-preset-bar">
    <PresetIconBox preset={entry.preset} />
    <div className="ccs-preset-summary">
      <strong title={name}>{name}</strong>
    </div>
    <button type="button" className="ccs-text-button" onClick={onChange} disabled={disabled}>更换</button>
  </div>;
}

function PresetPicker({ entries, onPick, disabled }: {
  entries: PresetEntry[]; onPick: (id: string) => void; disabled?: boolean;
}) {
  const [query, setQuery] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);
  const matching = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return entries.filter(({ preset }) =>
      [preset.name, preset.websiteUrl, ...preset.searchTerms]
        .some((value) => value.toLowerCase().includes(normalized)));
  }, [entries, query]);
  const searching = query.trim().length > 0;
  const customRow = <PresetRow
    icon={<PresetIconBox />}
    name="自定义"
    onClick={() => onPick('custom')}
    disabled={disabled}
  />;

  return <div data-preset-selector="" className="ccs-preset-picker">
    <div className="ccs-preset-search">
      <Search aria-hidden="true" size={17} />
      <input ref={searchRef} value={query} disabled={disabled}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && query) {
            event.preventDefault(); setQuery('');
          }
        }}
        placeholder="搜索提供方" aria-label="搜索提供方" />
      {query && <button type="button" aria-label="清除搜索" disabled={disabled} onClick={() => {
        setQuery(''); searchRef.current?.focus();
      }}><X size={16} /></button>}
    </div>
    {searching && matching.length === 0
      ? <div className="ccs-preset-no-results">
        <p>没有找到“{query.trim()}”</p>
        {customRow}
      </div>
      : <section aria-label="官方提供方" className="ccs-preset-grid">
        {matching.map(({ id, preset }) => <PresetRow key={id}
          icon={<PresetIconBox preset={preset} />} name={preset.name}
          detail={preset.detail} onClick={() => onPick(id)} disabled={disabled} />)}
        {customRow}
      </section>}
  </div>;
}

function PresetRow({ icon, name, detail, selected = false, onClick, disabled }: {
  icon: ReactNode; name: string; detail?: string; selected?: boolean;
  onClick: () => void; disabled?: boolean;
}) {
  return <button type="button" onClick={onClick}
    aria-current={selected || undefined} aria-label={name} aria-description={detail}
    className="ccs-preset-row" disabled={disabled}>
    {icon}
    <span className="ccs-preset-summary">
      <strong title={name}>{name}</strong>
      {detail && <span title={detail}>{detail}</span>}
    </span>
  </button>;
}
