import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { EditorView } from '@codemirror/view';
import { useState } from 'react';
import { afterEach, expect, test, vi } from 'vitest';
import LearningCompositionV2 from './LearningCompositionV2';
import type { CompositionDraftV2, CompositionIntentV2, CompositionV2, LearningCompositionV2Props } from './LearningCompositionV2';
import { initialCompositionDraftV2 } from './composition-v2-runtime.mjs';

afterEach(cleanup);
const binding = { id: 'artifact', content_ref: { owner: 'tutor' as const, id: 'presentation', revision: 1, public_identity: 'digest' } };
const definition = (): CompositionV2 => ({
  schema_version: 'learning_composition.v2', title: 'Interact',
  states: { answer: { type: 'choice', value: [] }, code: { type: 'code', value: 'print(1)' } },
  components: [
    { id: 'answer', component: 'ChoiceAnswer', props: { label: 'Select', options: [{ id: 'A', text: 'same' }, { id: 'B', text: 'same' }], state: 'answer' } },
    { id: 'send', component: 'ArtifactAction', props: { label: 'Submit', event: 'submit_answer', for_component: 'answer', primary: true } },
    { id: 'editor', component: 'CodeEditor', props: { label: 'Code', state: 'code' } },
    { id: 'run', component: 'ArtifactAction', props: { label: 'Check', event: 'check_code', for_component: 'editor', primary: true } },
    { id: 'result', component: 'ResultFeedback', props: { label: 'Result', for_component: 'editor' } },
  ],
});

function Host({ value, action = vi.fn(), allowed = true, ...props }: {
  value: CompositionV2; action?: (intent: CompositionIntentV2) => void; allowed?: boolean;
} & Pick<LearningCompositionV2Props,
  'codeWorkbenches' | 'beforeComponent' | 'afterComponent' | 'readOnly' | 'status' | 'lockedComponents'>) {
  const [draft, setDraft] = useState<CompositionDraftV2>(() => initialCompositionDraftV2(value));
  return <LearningCompositionV2 {...props} definition={value} binding={binding} draft={draft} onDraftChange={setDraft}
    onAction={action} allowedActions={allowed ? [
      { component_id: 'answer', event: 'submit_answer' }, { component_id: 'editor', event: 'check_code' },
    ] : []} />;
}

test('duplicate visible option labels preserve distinct response ids and clicks only emit intents', () => {
  const action = vi.fn();
  render(<Host value={definition()} action={action} />);
  fireEvent.click(screen.getAllByRole('radio')[1]);
  fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
  expect(action).toHaveBeenCalledWith({ type: 'submit_answer', component_id: 'answer', response: { type: 'choice', value: ['B'] } });
  expect(screen.queryByText('回答正确。')).toBeNull();
});

test('model action declarations never authorize host actions', () => {
  render(<Host value={definition()} allowed={false} />);
  expect((screen.getByRole('button', { name: 'Check' }) as HTMLButtonElement).disabled).toBe(true);
});

test('a teaching example can be edited without a practice owner or a run control', () => {
  const action = vi.fn();
  const value: CompositionV2 = {
    schema_version: 'learning_composition.v2', title: '改名字',
    states: { greeting: { type: 'code', value: 'string name = "小雨";' } },
    components: [{ id: 'greeting_editor', component: 'CodeEditor',
      props: { label: '名字', state: 'greeting' } }],
  };
  render(<Host value={value} action={action} allowed={false} />);
  const editor = screen.getByRole('textbox', { name: '名字' }) as HTMLTextAreaElement;
  fireEvent.change(editor, { target: { value: 'string name = "阿岚";' } });
  expect(editor.value).toBe('string name = "阿岚";');
  expect(screen.queryByRole('button', { name: /运行|检查|run|check/i })).toBeNull();
  expect(action).not.toHaveBeenCalled();
});

const codeWorkbenches = {
  editor: {
    title: 'Owner program', language: <span>Python</span>, tests: <p>Public sample</p>,
    tabs: [{ id: 'history', label: '运行记录', content: <p>Original attempts</p> }],
    hasResult: false, busy: false,
  },
};

test.each([false, true])('owner-bound code reuses the designed workbench with one editor and original action targets (diff port: %s)', (diffPort) => {
  const value = definition(), action = vi.fn();
  if (diffPort) value.components[2] = {
    id: 'editor', component: 'CodeDiff', props: { label: 'Code', state: 'code', before: 'print(1)' },
  };
  else value.components.push({
    id: 'diff', component: 'CodeDiff', props: { label: 'Starter comparison', state: 'code', before: 'print(1)' },
  });
  value.components.push(
    { id: 'controls', component: 'ActionGroup', props: { members: ['send', 'run'] } },
  );
  render(<Host value={value} action={action} codeWorkbenches={codeWorkbenches}
    beforeComponent={(id) => id === 'editor' ? <p>Published task</p> : null}
    afterComponent={(id) => id === 'editor' ? <p>Owner status</p> : null} />);
  const editor = screen.getByRole('textbox', { name: 'Code' });
  const workbench = editor.closest('.demo-workbench') as HTMLElement;
  expect(workbench).toBeTruthy();
  expect(document.querySelectorAll('[data-component-id="editor"]')).toHaveLength(1);
  expect(screen.getAllByRole('textbox', { hidden: true })).toHaveLength(1);
  expect(within(workbench).getByRole('region', { name: '题目与学习工具' }).textContent).toContain('Published task');
  expect(screen.getAllByRole('radio')[0].closest('.demo-workbench')).toBeNull();
  expect(screen.getAllByRole('button', { name: 'Check' })).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'Check' }).closest('.demo-workbench-runbar')).toBeTruthy();
  const codeView = EditorView.findFromDOM(editor)!;
  act(() => codeView.dispatch({ changes: { from: 0, to: codeView.state.doc.length, insert: 'print(17)' } }));
  const diff = screen.getByRole('button', { name: '切换Code修改对照' });
  fireEvent.click(diff);
  expect(diff.getAttribute('aria-pressed')).toBe('true');
  expect(codeView.state.doc.toString()).toBe('print(17)');
  expect(action).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Check' }));
  expect(action).toHaveBeenCalledExactlyOnceWith({
    type: 'check_code', component_id: 'editor', submission: { type: 'code', code: 'print(17)' },
  });
  expect(screen.getByRole('tab', { name: '运行结果' }).getAttribute('aria-selected')).toBe('true');
  fireEvent.click(screen.getByRole('tab', { name: '运行记录' }));
  expect(within(workbench).getByRole('tabpanel', { name: '运行记录' }).textContent).toContain('Original attempts');
});

test.each([
  ['no permission', { allowed: false }],
  ['unknown', { status: 'unknown' as const }],
  ['locked component', { lockedComponents: ['editor'] }],
  ['read only', { readOnly: true }],
])('workbench preserves the %s execution boundary', (_, props) => {
  const action = vi.fn();
  render(<Host value={definition()} codeWorkbenches={codeWorkbenches} action={action} {...props} />);
  const run = screen.getByRole('button', { name: 'Check' }) as HTMLButtonElement;
  expect(run.disabled).toBe(true);
  fireEvent.click(run);
  expect(action).not.toHaveBeenCalled();
});

test('HTML preview snapshots update only on an allowed local action and never submit or enable scripts', () => {
  const action = vi.fn();
  const value: CompositionV2 = {
    schema_version: 'learning_composition.v2', title: 'Static HTML',
    states: { html: { type: 'code', value: '<p>Original</p>' } },
    components: [
      { id: 'editor', component: 'CodeEditor', props: { label: 'HTML', state: 'html' } },
      { id: 'preview', component: 'IsolatedPreview', props: { title: 'Local safe preview', html_state: 'html' } },
      { id: 'refresh', component: 'ArtifactAction', props: { label: 'Preview draft', event: 'preview', for_component: 'preview' } },
    ],
  };
  function PreviewHost() {
    const [draft, setDraft] = useState<CompositionDraftV2>(() => initialCompositionDraftV2(value));
    return <LearningCompositionV2 definition={value} binding={binding} draft={draft}
      onDraftChange={setDraft} onAction={action}
      allowedActions={[{ component_id: 'preview', event: 'preview' }]} />;
  }
  render(<PreviewHost />);
  const frame = screen.getByTitle('Local safe preview') as HTMLIFrameElement;
  expect(frame.getAttribute('sandbox')).toBe('');
  fireEvent.change(screen.getByRole('textbox', { name: 'HTML' }), {
    target: { value: '<p>Changed</p><script>parent.bad()</script><img src="https://elsewhere.invalid/x">' },
  });
  expect(frame.srcdoc).toContain('Original');
  expect(frame.srcdoc).not.toContain('Changed');
  fireEvent.click(screen.getByRole('button', { name: 'Preview draft' }));
  expect(frame.srcdoc).toContain('Changed');
  expect(frame.srcdoc).not.toContain('<script');
  expect(frame.srcdoc).not.toContain('https://elsewhere.invalid');
  expect(frame.srcdoc).toContain("script-src 'none'");
  expect(action).not.toHaveBeenCalled();
});

const previewDefinition = (): CompositionV2 => ({
  schema_version: 'learning_composition.v2', title: 'Editable preview',
  states: {
    markup: { type: 'code', value: '<p>Original</p>' },
    style: { type: 'code', value: 'p { color: navy; }' },
    other: { type: 'code', value: 'print(1)' },
  },
  components: [
    { id: 'markup_editor', component: 'CodeEditor', props: { label: 'Markup draft', state: 'markup' } },
    { id: 'style_editor', component: 'CodeEditor', props: { label: 'Style draft', state: 'style' } },
    { id: 'canvas', component: 'IsolatedPreview', props: { title: 'Edited page', html_state: 'markup', css_state: 'style' } },
    { id: 'apply', component: 'ArtifactAction', props: { label: 'Apply page', event: 'preview', for_component: 'canvas', primary: true } },
    { id: 'close', component: 'ArtifactAction', props: { label: 'Close page', event: 'cancel', for_component: 'canvas' } },
    { id: 'controls', component: 'ActionGroup', props: { members: ['apply', 'close'] } },
    { id: 'other_editor', component: 'CodeEditor', props: { label: 'Unrelated code', state: 'other' } },
  ],
});

test('linked HTML and CSS use the designed tabbed workbench without duplicating editors or grouped actions', () => {
  const value = previewDefinition(), action = vi.fn();
  function PreviewHost() {
    const [draft, setDraft] = useState<CompositionDraftV2>(() => initialCompositionDraftV2(value));
    return <LearningCompositionV2 definition={value} binding={binding} draft={draft}
      onDraftChange={setDraft} onAction={action} practiceOnly
      afterComponent={(id) => id === 'canvas' ? <p>Owner observation controls</p> : null}
      allowedActions={[{ component_id: 'canvas', event: 'preview' }, { component_id: 'canvas', event: 'cancel' }]} />;
  }
  render(<PreviewHost />);
  const editor = screen.getByRole('region', { name: 'HTML CSS 编辑区' });
  const result = screen.getByRole('region', { name: 'HTML CSS 预览区' });
  const frame = within(result).getByTitle('Edited page') as HTMLIFrameElement;
  expect(editor.closest('.demo-html-workbench')).toBe(result.closest('.demo-html-workbench'));
  expect(within(editor).getByRole('tab', { name: 'HTML' }).getAttribute('aria-selected')).toBe('true');
  expect(screen.getAllByRole('textbox', { name: 'Markup draft', hidden: true })).toHaveLength(1);
  expect(screen.getAllByRole('textbox', { name: 'Style draft', hidden: true })).toHaveLength(1);
  expect(screen.getByRole('textbox', { name: 'Unrelated code' }).closest('.demo-html-workbench')).toBeNull();
  const apply = within(editor).getByRole('button', { name: 'Apply page' });
  expect(apply.closest('.demo-workbench-runbar')).toBeTruthy();
  expect(screen.getAllByRole('button', { name: 'Apply page' })).toHaveLength(1);
  expect(screen.queryByRole('button', { name: 'Close page' })).toBeNull();
  expect(screen.getByText('Owner observation controls').closest('.demo-html-workbench')).toBeNull();

  fireEvent.change(within(editor).getByRole('textbox', { name: 'Markup draft' }), { target: { value: '<p>Changed</p>' } });
  fireEvent.click(within(editor).getByRole('tab', { name: 'CSS' }));
  expect(within(editor).queryByRole('textbox', { name: 'Markup draft' })).toBeNull();
  fireEvent.change(within(editor).getByRole('textbox', { name: 'Style draft' }), { target: { value: 'p { color: teal; }' } });
  expect(frame.srcdoc).toContain('Original');
  expect(frame.srcdoc).toContain('color: navy');
  fireEvent.click(apply);
  expect(frame.srcdoc).toContain('Changed');
  expect(frame.srcdoc).toContain('color: teal');
  expect(apply.getAttribute('data-action-state')).toBe('completed');
  expect(action).not.toHaveBeenCalled();
  fireEvent.click(within(editor).getByRole('tab', { name: 'HTML' }));
  expect((within(editor).getByRole('textbox', { name: 'Markup draft' }) as HTMLTextAreaElement).value).toBe('<p>Changed</p>');
  fireEvent.change(within(editor).getByRole('textbox', { name: 'Markup draft' }), { target: { value: '<p>New draft</p>' } });
  expect(apply.getAttribute('data-action-state')).toBe('idle');
  expect(frame.srcdoc).toContain('Changed');
  expect(frame.srcdoc).not.toContain('New draft');
});

test.each(['ready', 'busy', 'unknown', 'cancelled'] as const)('preview workbench keeps host permission and %s state', (status) => {
  const value = previewDefinition(), draft = initialCompositionDraftV2(value), change = vi.fn();
  draft.previews.canvas = { html: String(draft.values.markup), css: String(draft.values.style) };
  render(<LearningCompositionV2 definition={value} binding={binding} draft={draft} onDraftChange={change}
    status={status} allowedActions={[]} />);
  const apply = screen.getByRole('button', { name: 'Apply page' }) as HTMLButtonElement;
  expect(apply.disabled).toBe(true);
  fireEvent.click(apply);
  expect(change).not.toHaveBeenCalled();
  if (status === 'cancelled' || status === 'unknown') expect(apply.getAttribute('data-action-state')).not.toBe('completed');
});

test('an oversized UTF-8 execution draft remains editable but cannot request the original runner', () => {
  render(<Host value={definition()} />);
  fireEvent.change(screen.getByRole('textbox', { name: 'Code' }), { target: { value: '汉'.repeat(4001) } });
  expect((screen.getByRole('button', { name: 'Check' }) as HTMLButtonElement).disabled).toBe(true);
});

test('only the matching artifact, content and code snapshot can display a result', () => {
  const value = definition(), draft = initialCompositionDraftV2(value);
  const result = {
    artifact_id: binding.id, content_ref: binding.content_ref, component_id: 'editor', client_action_id: 'action',
    result_id: 'result', type: 'code' as const, attempt_id: 'attempt',
    submission: { type: 'code' as const, code: 'print(1)' }, message: 'Actual owner receipt', columns: ['Output'], rows: [['1']],
  };
  const view = render(<LearningCompositionV2 definition={value} binding={binding} draft={draft} onDraftChange={vi.fn()} receipts={[result]} />);
  expect(screen.getByText('Actual owner receipt')).toBeTruthy();
  view.rerender(<LearningCompositionV2 definition={value} binding={binding}
    draft={{ ...draft, values: { ...draft.values, code: 'print(2)' } }} onDraftChange={vi.fn()} receipts={[result]} />);
  expect(screen.queryByText('Actual owner receipt')).toBeNull();
  expect(screen.getByText('草稿已修改，之前的结果不适用于当前内容。')).toBeTruthy();
  view.rerender(<LearningCompositionV2 definition={value} binding={{ ...binding, id: 'other' }}
    draft={draft} onDraftChange={vi.fn()} receipts={[result]} />);
  expect(screen.queryByText('Actual owner receipt')).toBeNull();
});

test('a submitted-code review annotates one canonical code view and never follows an unrelated draft or receipt', () => {
  const value: CompositionV2 = {
    schema_version: 'learning_composition.v2', title: 'Submitted program review',
    states: { code: { type: 'code', value: 'values = []\nprint(0)', read_only: true } },
    components: [
      { id: 'source', component: 'CodeBlock', props: { label: 'Pinned submission', state: 'code' } },
      { id: 'notes', component: 'ReviewFinding', props: { label: 'Checked comments', for_component: 'source' } },
    ],
  };
  const draft = initialCompositionDraftV2(value);
  draft.values.code = 'a different unsaved draft';
  const receipt = {
    artifact_id: binding.id, content_ref: binding.content_ref, component_id: 'source',
    result_id: 'presentation', client_action_id: null, type: 'review' as const,
    message: 'Teaching, not a new score',
    findings: [{ line: 2, content: 'This ignores the input.' }, { line: 2, content: 'Sum the values.' }],
  };
  const shown = render(<LearningCompositionV2 definition={value} binding={binding}
    draft={draft} onDraftChange={vi.fn()} receipts={[receipt]} />);
  expect(document.querySelectorAll('[data-learning-component="review-finding"]')).toHaveLength(1);
  expect(screen.getAllByText('print(0)')).toHaveLength(1);
  expect(screen.getByText('This ignores the input.')).toBeTruthy();
  expect(screen.getByText('Sum the values.')).toBeTruthy();
  expect(screen.queryByText('a different unsaved draft')).toBeNull();
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(screen.queryByRole('button')).toBeNull();
  shown.rerender(<LearningCompositionV2 definition={value}
    binding={{ ...binding, content_ref: { ...binding.content_ref, revision: 2 } }}
    draft={draft} onDraftChange={vi.fn()} receipts={[receipt]} />);
  expect(screen.queryByText('This ignores the input.')).toBeNull();
  expect(document.querySelector('[data-learning-component="review-finding"]')).toBeNull();
  expect(screen.getByLabelText('Pinned submission').textContent).toBe('values = []\nprint(0)');
});

test('review line edits must be saved before whole-review submission; saved notes are not grades', () => {
  const action = vi.fn();
  const value: CompositionV2 = {
    schema_version: 'learning_composition.v2', title: 'Review',
    states: { code: { type: 'code', value: 'return x', read_only: true }, notes: { type: 'annotations', value: [] } },
    components: [
      { id: 'review', component: 'LineRangeAnswer', props: { label: 'Review code', code_state: 'code', state: 'notes' } },
      { id: 'send', component: 'ArtifactAction', props: { label: 'Submit review', event: 'submit_review', for_component: 'review' } },
    ],
  };
  function ReviewHost() {
    const [draft, setDraft] = useState<CompositionDraftV2>(() => initialCompositionDraftV2(value));
    return <LearningCompositionV2 definition={value} binding={binding} draft={draft} onDraftChange={setDraft}
      onAction={action} allowedActions={[{ component_id: 'review', event: 'submit_review' }]} />;
  }
  render(<ReviewHost />);
  fireEvent.click(screen.getByRole('button', { name: '第 1 行：return x' }));
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'x is not defined' } });
  expect((screen.getByRole('button', { name: 'Submit review' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '保存第 1 行批注' }));
  expect(action).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Submit review' }));
  expect(action).toHaveBeenCalledWith({ type: 'submit_review', component_id: 'review', annotations: [{ line: 1, reason: 'x is not defined' }] });
});

test('parameter and algorithm views share one deterministic timeline instead of duplicate players', () => {
  const value: CompositionV2 = {
    schema_version: 'learning_composition.v2', title: 'Search',
    states: { step: { type: 'playback', value: 0 }, target: { type: 'number', value: 2 } },
    inputs: { numbers: { type: 'binary_search', values: [1, 2, 3], target_state: 'target' } },
    components: [
      { id: 'player', component: 'AlgorithmPlayer', props: { label: 'Search trace', state: 'step', algorithm: 'binary_search', input: 'numbers' } },
      { id: 'view', component: 'AlgorithmSequence', props: { label: 'Sequence', timeline: 'player' } },
      { id: 'control', component: 'ParameterControl', props: { label: 'Target', state: 'target', minimum: 0, maximum: 9 } },
    ],
  };
  render(<Host value={value} />);
  expect(document.querySelectorAll('[data-learning-component="algorithm-player"]')).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Search trace：下一步' }));
  expect(document.querySelector('[data-learning-component="algorithm-player"]')?.getAttribute('data-step')).toBe('1');
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Target' }), { target: { value: '9' } });
  expect(document.querySelector('[data-learning-component="algorithm-player"]')?.getAttribute('data-step')).toBe('0');
});

test('step player and sequence share the same zero-based observation, including the final step', () => {
  const value: CompositionV2 = {
    schema_version: 'learning_composition.v2', title: 'Shared sequence',
    states: { step: { type: 'playback', value: 0 } },
    components: [
      { id: 'sequence', component: 'SequenceDiagram', props: {
        label: 'Messages', state: 'step',
        participants: [{ id: 'client', label: 'Client' }, { id: 'owner', label: 'Owner' }],
        steps: [
          { id: 'send', source: 'client', target: 'owner', label: 'Send' },
          { id: 'commit', source: 'owner', target: 'owner', label: 'Commit' },
          { id: 'receipt', source: 'owner', target: 'client', label: 'Receipt' },
        ],
      } },
      { id: 'steps', component: 'StepPlayer', props: {
        label: 'Shared steps', state: 'step', items: ['Send', 'Commit', 'Receipt'],
      } },
    ],
  };
  const view = render(<Host value={value} />);
  const sequence = within(screen.getByRole('group', { name: 'Messages' }));
  const current = () => document.querySelector('[data-learning-component="step-player"] [aria-current="step"]')?.textContent;
  expect(current()).toBe('Send');
  expect(sequence.getByRole('button', { name: '第 1 步：Send' }).getAttribute('aria-pressed')).toBe('true');
  fireEvent.click(screen.getByRole('button', { name: '观察下一步' }));
  expect(current()).toBe('Commit');
  expect(sequence.getByRole('button', { name: '第 2 步：Commit' }).getAttribute('aria-pressed')).toBe('true');
  fireEvent.click(sequence.getByRole('button', { name: '第 3 步：Receipt' }));
  expect(current()).toBe('Receipt');
  expect((screen.getByRole('button', { name: '观察下一步' }) as HTMLButtonElement).disabled).toBe(true);
  const restored = initialCompositionDraftV2(value);
  restored.values.step = 3;
  view.rerender(<LearningCompositionV2 definition={value} binding={binding} draft={restored}
    onDraftChange={vi.fn()} />);
  expect(current()).toBe('Receipt');
  expect(screen.getByRole('button', { name: '第 3 步：Receipt' }).getAttribute('aria-pressed')).toBe('true');
});

test('cancelling a composition pauses its in-flight local step player', () => {
  const value: CompositionV2 = {
    schema_version: 'learning_composition.v2', title: 'Local steps',
    states: { step: { type: 'playback', value: 0 } },
    components: [{ id: 'steps', component: 'StepPlayer', props: {
      label: 'Steps', state: 'step', items: ['Send', 'Commit', 'Receipt'],
    } }],
  };
  function PlaybackHost({ cancelled = false }) {
    const [draft, setDraft] = useState<CompositionDraftV2>(() => initialCompositionDraftV2(value));
    return <LearningCompositionV2 definition={value} binding={binding} draft={draft}
      onDraftChange={setDraft} status={cancelled ? 'cancelled' : 'ready'} />;
  }
  const view = render(<PlaybackHost />);
  fireEvent.click(screen.getByRole('button', { name: '自动播放' }));
  expect(screen.getByRole('button', { name: '暂停播放' })).toBeTruthy();
  view.rerender(<PlaybackHost cancelled />);
  expect(screen.queryByRole('button', { name: '暂停播放' })).toBeNull();
});

test('document hiding pauses both local playback controls without advancing their shared drafts', () => {
  const value: CompositionV2 = {
    schema_version: 'learning_composition.v2', title: 'Visible observation',
    states: {
      algorithm: { type: 'playback', value: 0 }, steps: { type: 'playback', value: 0 },
      target: { type: 'number', value: 3 },
    },
    inputs: { numbers: { type: 'binary_search', values: [1, 3, 5], target_state: 'target' } },
    components: [
      { id: 'algorithm', component: 'AlgorithmPlayer', props: {
        label: 'Search trace', state: 'algorithm', algorithm: 'binary_search', input: 'numbers',
      } },
      { id: 'steps', component: 'StepPlayer', props: {
        label: 'Steps', state: 'steps', items: ['Send', 'Commit', 'Receipt'],
      } },
    ],
  };
  render(<Host value={value} />);
  fireEvent.click(screen.getByRole('button', { name: 'Search trace：播放' }));
  fireEvent.click(screen.getByRole('button', { name: '自动播放' }));
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  try {
    fireEvent(document, new Event('visibilitychange'));
    expect(screen.queryByRole('button', { name: 'Search trace：暂停' })).toBeNull();
    expect(screen.queryByRole('button', { name: '暂停播放' })).toBeNull();
    expect(document.querySelector('[data-learning-component="algorithm-player"]')?.getAttribute('data-step')).toBe('0');
    expect(document.querySelector('[data-learning-component="step-player"] [aria-current="step"]')?.textContent).toBe('Send');
  } finally {
    hidden.mockRestore();
  }
});
