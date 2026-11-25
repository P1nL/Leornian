import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NodeTeachingWindow, { NODE_WINDOW_MS } from './NodeTeachingWindow';

function surface(onExpire: () => void, enabled = true, identity = 'first', after: string | null = null) {
  return <main data-chat-pane><button>正文</button><section data-artifact-id="exercise"><textarea aria-label="练习草稿" /></section>
    <div className="demo-composer-surface"><textarea aria-label="教学输入" /><NodeTeachingWindow
      identity={identity} enabled={enabled} after={after} onExpire={onExpire} /></div></main>;
}
const tick = async (time: number) => { await act(async () => { vi.advanceTimersByTime(time); }); };
const focus = (element: HTMLElement) => act(() => { element.focus(); });
const blur = async (element: HTMLElement) => { await act(async () => { element.blur(); }); };

beforeEach(() => { vi.useFakeTimers(); vi.spyOn(document, 'hasFocus').mockReturnValue(true); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

test('hover or clicking an empty editor stops the window; leaving gives a full new window', async () => {
  const expire = vi.fn();
  render(surface(expire));
  const editor = screen.getByLabelText('教学输入'), frame = editor.parentElement!;
  await tick(NODE_WINDOW_MS - 1);
  fireEvent.pointerEnter(frame);
  await tick(NODE_WINDOW_MS * 2);
  fireEvent.pointerDown(editor); focus(editor); fireEvent.pointerUp(editor); fireEvent.pointerLeave(frame);
  await tick(NODE_WINDOW_MS * 2);
  expect(expire).not.toHaveBeenCalled();
  await blur(editor);
  await tick(NODE_WINDOW_MS - 1);
  expect(expire).not.toHaveBeenCalled();
  await tick(1);
  await tick(NODE_WINDOW_MS * 2);
  expect(expire).toHaveBeenCalledOnce();
});

test('programmatic focus does not take over; tab focus, IME, drafts and exercise editing do', async () => {
  const expire = vi.fn();
  const view = render(surface(expire));
  const editor = screen.getByLabelText('教学输入'), practice = screen.getByLabelText('练习草稿');
  focus(editor);
  await tick(NODE_WINDOW_MS);
  expect(expire).toHaveBeenCalledOnce();
  await blur(editor);
  view.rerender(surface(expire, true, 'second'));
  fireEvent.keyDown(document.body, { key: 'Tab' }); focus(editor); fireEvent.keyUp(editor, { key: 'Tab' });
  fireEvent.compositionStart(editor); await tick(NODE_WINDOW_MS);
  fireEvent.compositionEnd(editor);
  fireEvent.input(editor, { target: { value: ' ' } }); await blur(editor);
  await tick(NODE_WINDOW_MS * 2);
  expect(expire).toHaveBeenCalledTimes(1);
  fireEvent.input(editor, { target: { value: '' } }); focus(practice);
  await tick(NODE_WINDOW_MS * 2);
  expect(expire).toHaveBeenCalledTimes(1);
  await blur(practice); await tick(NODE_WINDOW_MS);
  expect(expire).toHaveBeenCalledTimes(2);
});

test('waits for the delivered text to mount and never catches up across background or node changes', async () => {
  const expire = vi.fn();
  const view = render(surface(expire, true, 'one:after', 'turn-1'));
  await tick(NODE_WINDOW_MS * 2);
  expect(expire).not.toHaveBeenCalled();
  await act(async () => {
    const reply = document.createElement('div'); reply.dataset.nodeReply = 'turn-1';
    view.container.querySelector('main')!.append(reply);
  });
  await tick(NODE_WINDOW_MS - 1);
  fireEvent(window, new window.Event('blur'));
  await tick(NODE_WINDOW_MS * 2);
  fireEvent(window, new window.Event('focus'));
  await tick(NODE_WINDOW_MS - 1);
  view.rerender(surface(expire, false, 'two'));
  await tick(NODE_WINDOW_MS * 2);
  expect(expire).not.toHaveBeenCalled();
  view.rerender(surface(expire, true, 'two'));
  await tick(NODE_WINDOW_MS); expect(expire).toHaveBeenCalledOnce();
});
