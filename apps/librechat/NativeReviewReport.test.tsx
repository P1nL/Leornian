import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { NativeReviewReport } from './NativeReviewReport';

afterEach(cleanup);

const completion = {
  id: 'completion', artifact_id: 'artifact', component_id: 'submitted', presentation_id: 'presentation',
  content_identity: 'digest', attempt_id: 'original-attempt', evaluation_id: 'original-evaluation',
  evidence_kind: 'learner_review_report.v1', completed_at: '2026-11-06T09:10:11Z',
};
const report = {
  component_id: 'submitted', state: 'ready', allowed_actions: ['complete_review'], completion: null,
} as const;

test('reading confirmation is an explicit component action, not a mount or refresh side effect', () => {
  const onCommand = vi.fn();
  const view = render(<NativeReviewReport report={report as any} blocked={false} onCommand={onCommand} />);
  view.rerender(<NativeReviewReport report={report as any} blocked={false} onCommand={onCommand} />);
  expect(onCommand).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '我已阅读本次评审' }));
  expect(onCommand).toHaveBeenCalledTimes(1);
  expect(onCommand).toHaveBeenCalledWith({ action: 'complete_review', component_id: 'submitted' });
});

test('saved confirmation shows the server time and remains historical after cancellation', () => {
  const onCommand = vi.fn(), saved = { ...report, state: 'completed', allowed_actions: [], completion };
  const view = render(<NativeReviewReport report={saved as any} blocked={false} onCommand={onCommand} />);
  expect(screen.getByText('已确认阅读本次评审')).toBeTruthy();
  expect(document.querySelector('time')?.getAttribute('datetime')).toBe(completion.completed_at);
  expect(screen.queryByRole('button', { name: '我已阅读本次评审' })).toBeNull();
  view.rerender(<NativeReviewReport report={{ ...saved, state: 'cancelled' } as any}
    blocked onCommand={onCommand} />);
  expect(screen.getByText('本次评审已取消。')).toBeTruthy();
  expect(document.querySelector('time')?.getAttribute('datetime')).toBe(completion.completed_at);
  expect(onCommand).not.toHaveBeenCalled();
});

test('pending and unknown confirmation uses the original receipt rather than another command', () => {
  const onCommand = vi.fn();
  render(<NativeReviewReport report={report as any} blocked pending onCommand={onCommand} />);
  expect(screen.getByRole('button', { name: '我已阅读本次评审' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '我已阅读本次评审' }));
  expect(screen.getByText(/阅读确认尚待核对/)).toBeTruthy();
  expect(screen.queryByText('已确认阅读本次评审')).toBeNull();
  expect(onCommand).not.toHaveBeenCalled();
});

test('a cancelled report offers no confirmation action', () => {
  const onCommand = vi.fn();
  render(<NativeReviewReport report={{ ...report, state: 'cancelled', allowed_actions: [] } as any}
    blocked={false} onCommand={onCommand} />);
  expect(screen.getByText('本次评审已取消。')).toBeTruthy();
  expect(screen.queryByRole('button', { name: '我已阅读本次评审' })).toBeNull();
  expect(onCommand).not.toHaveBeenCalled();
});
