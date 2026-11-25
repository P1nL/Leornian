// Adapted from CC Switch FetchedModelPicker.tsx; see CCS-UPSTREAM.md.
import { useState } from 'react';
import { Search } from 'lucide-react';
import { Action } from './LearningUI';

export interface FetchedModelSelection { add: string[]; remove: string[] }
export interface PresetModel { id: string; label: string }

export default function FetchedModelPicker({
  models, configuredModelIds, onApply, onCancel,
}: {
  models: PresetModel[];
  configuredModelIds: string[];
  onApply: (selection: FetchedModelSelection) => void;
  onCancel: () => void;
}) {
  const configured = [...new Set(configuredModelIds.map((id) => id.trim()).filter(Boolean))];
  const [query, setQuery] = useState('');
  const [onlySelected, setOnlySelected] = useState(false);
  const [draft, setDraft] = useState<Set<string>>(() => new Set(configured));
  const normalized = query.trim().toLowerCase();
  const visible = models.filter((model) => (!onlySelected || draft.has(model.id)) &&
    (!normalized || model.id.toLowerCase().includes(normalized) ||
      model.label.toLowerCase().includes(normalized)));
  const visibleIds = visible.map((model) => model.id);
  const selectedCount = models.filter((model) => draft.has(model.id)).length;
  const setChecked = (ids: string[], checked: boolean) => setDraft((prev) => {
    const next = new Set(prev);
    for (const id of ids) {
      if (checked) next.add(id);
      else next.delete(id);
    }
    return next;
  });
  const apply = () => {
    const configuredSet = new Set(configured);
    onApply({
      add: models.map((model) => model.id).filter((id) => draft.has(id) && !configuredSet.has(id)),
      remove: configured.filter((id) => !draft.has(id)),
    });
  };

  return <section className="ccs-model-picker" aria-label="选择预设模型">
    <div className="ccs-preset-search">
      <Search size={17} aria-hidden="true" />
      <input aria-label="搜索模型" placeholder="搜索模型或用途" value={query}
        onChange={(event) => setQuery(event.target.value)} />
    </div>
    <div className="ccs-model-toolbar">
      <label className="demo-choice"><input type="checkbox" checked={onlySelected}
        onChange={(event) => setOnlySelected(event.target.checked)} />只看已选</label>
      <span>已选 {selectedCount} / {models.length}</span>
      <button type="button" className="ccs-text-button" disabled={!visibleIds.length}
        onClick={() => setChecked(visibleIds, true)}>选择当前结果</button>
    </div>
    <ul className="ccs-model-options">
      {visible.map(({ id, label }) => <li key={id}>
        <label className="demo-choice">
          <input type="checkbox" aria-label={id} checked={draft.has(id)}
            onChange={(event) => setChecked([id], event.target.checked)} />
        <span><code>{id}</code><span>{label}</span></span>
        </label>
      </li>)}
    </ul>
    {!visible.length && <p className="demo-muted">没有匹配的模型。</p>}
    <div className="demo-actions">
      <Action onClick={onCancel}>取消选择</Action>
      <Action disabled={!selectedCount} onClick={apply}>应用模型选择</Action>
    </div>
  </section>;
}
