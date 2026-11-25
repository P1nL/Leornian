import { useEffect, useRef } from 'react';
import type { CSSProperties } from 'react';
import { Compartment, EditorState, StateEffect, StateField } from '@codemirror/state';
import type { Range } from '@codemirror/state';
import { Decoration, EditorView, GutterMarker, WidgetType, gutter, keymap } from '@codemirror/view';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { inlineDiffModel } from './component-utils.mjs';

const configureDiff = StateEffect.define<{ before: string; enabled: boolean }>();

class RemovedLines extends WidgetType {
  constructor(readonly texts: string[], readonly numbers: number[]) { super(); }
  eq(other: RemovedLines) { return this.texts.join('\n') === other.texts.join('\n') && this.numbers.join() === other.numbers.join(); }
  toDOM() {
    const element = document.createElement('div');
    element.className = 'demo-inline-removed';
    element.setAttribute('aria-label', '删除的旧代码，只读');
    element.contentEditable = 'false';
    for (const text of this.texts) {
      const row = document.createElement('div');
      row.className = 'demo-inline-removed-row';
      row.textContent = text || ' ';
      element.appendChild(row);
    }
    return element;
  }
  ignoreEvent() { return true; }
}

function diffState(state: EditorState, config: { before: string; enabled: boolean }) {
  const model = config.enabled ? inlineDiffModel(config.before, state.doc.toString()) : { lines: [], deletions: [] };
  const ranges: Range<Decoration>[] = [];
  for (const line of model.lines) {
    if (line.kind === 'added') ranges.push(Decoration.line({ class: 'demo-inline-added' }).range(state.doc.line(line.afterLine).from));
  }
  for (const deletion of model.deletions) {
    ranges.push(Decoration.widget({
      widget: new RemovedLines(deletion.rows.map((row) => row.text), deletion.rows.map((row) => row.beforeLine)),
      block: true, side: deletion.atLine === null ? 1 : -1,
    }).range(deletion.atLine === null ? state.doc.length : state.doc.line(deletion.atLine).from));
  }
  return { ...config, model, decorations: Decoration.set(ranges, true) };
}

const diffField = StateField.define({
  create: (state) => diffState(state, { before: '', enabled: false }),
  update(value, transaction) {
    let config = value;
    for (const effect of transaction.effects) if (effect.is(configureDiff)) config = { ...value, ...effect.value };
    return transaction.docChanged || config !== value ? diffState(transaction.state, config) : value;
  },
  provide: (field) => EditorView.decorations.from(field, (value) => value.decorations),
});

class Numbers extends GutterMarker {
  constructor(readonly numbers: (number | null)[], readonly removed = false) { super(); }
  eq(other: Numbers) { return this.numbers.join() === other.numbers.join() && this.removed === other.removed; }
  toDOM() {
    const element = document.createElement('span');
    element.className = `demo-inline-number-stack${this.removed ? ' demo-inline-deleted-number' : ''}`;
    for (const number of this.numbers) {
      const row = document.createElement('span');
      row.className = 'demo-inline-number-row';
      const digit = document.createElement('span');
      digit.className = 'demo-inline-number-digit';
      digit.textContent = number === null ? '\u00a0' : String(number);
      row.appendChild(digit);
      element.appendChild(row);
    }
    return element;
  }
}

const numberGutter = (old: boolean) => gutter({
  class: old ? 'demo-inline-old-gutter' : 'demo-inline-current-gutter',
  initialSpacer: () => new Numbers([99]),
  lineMarker(view, line) {
    const number = view.state.doc.lineAt(line.from).number;
    if (!old) return new Numbers([number]);
    return new Numbers([view.state.field(diffField).model.lines[number - 1]?.beforeLine ?? null]);
  },
  widgetMarker: (_view, widget) => widget instanceof RemovedLines
    ? new Numbers(old ? widget.numbers : widget.numbers.map(() => null), true) : null,
  lineMarkerChange: (update) => update.docChanged || update.startState.field(diffField) !== update.state.field(diffField),
});

export default function InlineCodeEditor({ label, value, before, showDiff, onChange, readOnly = false }: {
  label: string; value: string; before: string; showDiff: boolean;
  onChange?: (value: string) => void; readOnly?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const change = useRef(onChange);
  change.current = onChange;
  const access = useRef(new Compartment());
  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({ doc: value, extensions: [
        history(), keymap.of([indentWithTab, ...defaultKeymap, ...historyKeymap]),
        diffField, numberGutter(true), numberGutter(false),
        access.current.of([
          EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly),
          EditorView.contentAttributes.of({ 'aria-label': label, 'aria-multiline': 'true', spellcheck: 'false' }),
        ]),
        EditorView.updateListener.of((update) => { if (update.docChanged) change.current?.(update.state.doc.toString()); }),
      ] }),
    });
    view.current = editor;
    return () => { view.current = null; editor.destroy(); };
  }, []);
  useEffect(() => {
    const editor = view.current;
    if (!editor) return;
    if (value !== editor.state.doc.toString()) editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
  }, [value]);
  useEffect(() => {
    view.current?.dispatch({ effects: configureDiff.of({ before, enabled: showDiff }) });
  }, [before, showDiff]);
  useEffect(() => {
    view.current?.dispatch({ effects: access.current.reconfigure([
      EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly),
      EditorView.contentAttributes.of({ 'aria-label': label, 'aria-multiline': 'true', spellcheck: 'false' }),
    ]) });
  }, [readOnly, label]);
  const digits = Math.max(2, String(Math.max(value.split('\n').length, before.split('\n').length)).length);
  return <div ref={host} className="demo-inline-editor" data-diff={showDiff}
    style={{ '--demo-line-digits': digits } as CSSProperties} />;
}
