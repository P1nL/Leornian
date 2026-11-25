import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NativeRouteConfirmation from './NativeRouteConfirmation';

const native = vi.hoisted(() => ({
  state: {} as any, request: vi.fn(), write: vi.fn(), refresh: vi.fn(),
  navigate: vi.fn(), reconcile: vi.fn(),
}));
vi.mock('./native-client.mjs', () => ({
  nativeRequest: native.request,
  nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state, write: native.write,
    refresh: native.refresh, reconcile: native.reconcile,
  },
}));
vi.mock('react-router-dom', () => ({
  useNavigate: () => native.navigate, useLocation: () => ({ search: '?stage=planning' }),
}));

const base = {
  recipe_id: 'python-standard.v1', recipe_revision: 1, title: 'Python 标准库项目',
  profile: 'project-stdio.v1', language: 'python', dialect: null, toolchains: ['Python 3.12'],
  dependency_lock: [], sources: ['https://registry-1.docker.io'],
};
const flask = {
  ...base, recipe_id: 'python-flask.v1', title: 'Python / Flask 受控项目',
  dependency_lock: ['Flask==3.1.2'],
};
let manifest: any;

beforeEach(() => {
  sessionStorage.clear();
  native.state = { pending: [], snapshot: {
    actor: { id: 'actor' }, conversations: [{ id: 'conversation', goal_id: 'goal' }],
    runs: [], teaching_sessions: [],
    plans: [{ id: 'plan', goal_id: 'goal', active: null, latest: {
      revision: 1, document: { nodes: [{ key: 'first', title: '基础' }] },
    } }],
  } };
  manifest = {
    plan_id: 'plan', plan_revision: 1, requirements: [base, flask],
    automatic_recipe_ids: [base.recipe_id], consent_required: [flask], demands: [],
    gaps: [], engine: { status: 'ready' },
  };
  native.request.mockReset().mockImplementation(async (path: string) =>
    path.includes('/environment-requirements/') ? structuredClone(manifest) : null);
  native.write.mockReset().mockImplementation(async (path: string) =>
    path.endsWith('/actions') ? { revision: 1 } : {});
  native.refresh.mockReset().mockResolvedValue(undefined);
  native.navigate.mockReset();
  native.reconcile.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

async function open() {
  render(<NativeRouteConfirmation conversationId="conversation" />);
  const button = screen.getByRole('button', { name: '确认路线，开始学习' }) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(button);
  await screen.findByRole('dialog', { name: '本路线的学习环境' });
}

test('confirmation opens a button popover and only its explicit install action submits the full shown list', async () => {
  await open();
  expect(screen.getByText('系统自动安排专用隔离存储，不影响你现有的软件。')).toBeTruthy();
  expect(screen.queryByLabelText('安装位置')).toBeNull();
  expect(screen.getByRole('button', { name: '查看安装详情' }).getAttribute('aria-expanded')).toBe('false');
  fireEvent.click(screen.getByRole('button', { name: '确认路线并安装' }));
  await waitFor(() => expect(native.navigate).toHaveBeenCalledOnce());
  expect(native.write.mock.calls[0].slice(0, 2)).toEqual([
    '/v1/plans/plan/confirm', { expected_revision: 1, environment_requirements: [base, flask] },
  ]);
});

test('plain confirmation preserves the route without consenting to framework installation', async () => {
  await open();
  fireEvent.click(screen.getByRole('button', { name: '仅确认路线' }));
  await waitFor(() => expect(native.navigate).toHaveBeenCalledOnce());
  expect(native.write.mock.calls[0].slice(0, 2)).toEqual([
    '/v1/plans/plan/confirm', { expected_revision: 1 },
  ]);
  expect(native.write.mock.calls.some(([path]) => path.includes('/environment-demands/'))).toBe(false);
});

test('a route package set keeps its exact declaration when installation is requested later', async () => {
  const course = {
    ...base, recipe_id: 'course-typescript-example.v1', language: 'typescript',
    title: '阅读清单课程依赖', dependency_lock: ['dayjs@1.11.13'],
    course_environment: {
      language: 'typescript', title: '阅读清单课程依赖', build: 'stdio',
      dependencies: [{ name: 'dayjs', version: '1.11.13' }],
    },
  };
  native.state.snapshot.plans[0].active = native.state.snapshot.plans[0].latest;
  manifest.requirements = [course]; manifest.consent_required = [course];
  native.write.mockImplementation(async (path: string) => path === '/v1/environment-demands'
    ? { id: 'course-demand', requirement: course, decision: null,
      requirement_revision: 1, decision_revision: 0 }
    : {});
  render(<NativeRouteConfirmation conversationId="conversation" />);
  fireEvent.click(await screen.findByRole('button', { name: '学习环境 · 待允许安装' }));
  fireEvent.click(await screen.findByRole('button', { name: '安装所需环境' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(2));
  expect(native.write.mock.calls[0][1]).toEqual({
    recipe_id: course.recipe_id, course_environment: course.course_environment,
    plan_id: 'plan', plan_revision: 1, expected_requirement_revision: 0,
  });
});

test('base-only routes do not ask for package-by-package consent', async () => {
  manifest.requirements = [base]; manifest.consent_required = [];
  render(<NativeRouteConfirmation conversationId="conversation" />);
  const button = screen.getByRole('button', { name: '确认路线，开始学习' }) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  await waitFor(() => expect(native.navigate).toHaveBeenCalledOnce());
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(native.write.mock.calls[0][1]).toEqual({ expected_revision: 1 });
});

test('a deferred confirmed route offers one installation action with the original demand CAS', async () => {
  native.state.snapshot.plans[0].active = native.state.snapshot.plans[0].latest;
  manifest.demands = [{
    id: 'flask-demand', requirement: flask, requirement_revision: 2, decision_revision: 0,
    decision: null, plan_id: 'plan', plan_revision: 1, status: 'waiting_authorization',
  }];
  render(<NativeRouteConfirmation conversationId="conversation" />);
  fireEvent.click(await screen.findByRole('button', { name: '学习环境 · 待允许安装' }));
  fireEvent.click(await screen.findByRole('button', { name: '安装所需环境' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledOnce());
  expect(native.write.mock.calls[0].slice(0, 2)).toEqual([
    '/v1/environment-demands/flask-demand/decisions',
    { decision: 'allow', expected_requirement_revision: 2, expected_decision_revision: 0 },
  ]);
  expect(native.navigate).not.toHaveBeenCalled();
});

test('unresolved installation blocks a new decision and offers only original-receipt reconciliation', async () => {
  native.state.snapshot.plans[0].active = native.state.snapshot.plans[0].latest;
  manifest.demands = [{ id: 'flask-demand', requirement: flask, status: 'waiting_authorization' }];
  native.state.pending = [{
    path: '/v1/environment-demands/flask-demand/decisions', key: 'original-key', status: 'unknown',
  }];
  render(<NativeRouteConfirmation conversationId="conversation" />);
  fireEvent.click(await screen.findByRole('button', { name: '学习环境 · 待允许安装' }));
  const install = await screen.findByRole('button', { name: '安装所需环境' }) as HTMLButtonElement;
  expect(install.disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '核对原操作' }));
  await waitFor(() => expect(native.reconcile).toHaveBeenCalledWith('original-key'));
  expect(native.write).not.toHaveBeenCalled();
});

test.each([false, true])('late installation refreshes changed requirements, including a stopped base superset (%s)', async (stoppedBase) => {
  native.state.snapshot.plans[0].active = native.state.snapshot.plans[0].latest;
  const shown = stoppedBase ? base : { ...flask, dependency_lock: ['Flask==3.1.3'] };
  const old = {
    id: 'existing-demand', requirement: flask, requirement_revision: 2, decision_revision: 3,
    decision: stoppedBase ? 'revoke' : 'allow', plan_id: stoppedBase ? null : 'plan',
    plan_revision: stoppedBase ? null : 1, status: stoppedBase ? 'revoked' : 'ready',
  };
  manifest.requirements = [shown]; manifest.consent_required = [shown]; manifest.demands = [old];
  native.write.mockImplementation(async (path: string) => {
    if (path === '/v1/environment-demands') return {
      ...old, requirement: shown, requirement_revision: 3,
      decision: stoppedBase ? 'revoke' : null, status: 'waiting_authorization',
    };
    return {};
  });
  render(<NativeRouteConfirmation conversationId="conversation" />);
  fireEvent.click(await screen.findByRole('button', { name: '学习环境 · 待允许安装' }));
  fireEvent.click(await screen.findByRole('button', { name: '安装所需环境' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(2));
  expect(native.write.mock.calls[0].slice(0, 2)).toEqual([
    '/v1/environment-demands', {
      recipe_id: shown.recipe_id, plan_id: old.plan_id, plan_revision: old.plan_revision,
      expected_requirement_revision: 2,
    },
  ]);
  expect(native.write.mock.calls[0][2].lookup).toContain('/v1/environment-demand-requests/');
  expect(native.write.mock.calls[1].slice(0, 2)).toEqual([
    '/v1/environment-demands/existing-demand/decisions',
    { decision: 'allow', expected_requirement_revision: 3, expected_decision_revision: 3 },
  ]);
});

test('an unresolved requirement update is read by its original receipt without redispatch', async () => {
  native.state.snapshot.plans[0].active = native.state.snapshot.plans[0].latest;
  native.state.pending = [{
    path: '/v1/environment-demands', key: 'original-update', status: 'unknown',
    body: { recipe_id: flask.recipe_id, plan_id: 'plan', plan_revision: 1 },
  }];
  render(<NativeRouteConfirmation conversationId="conversation" />);
  fireEvent.click(await screen.findByRole('button', { name: '学习环境 · 待允许安装' }));
  expect((screen.getByRole('button', { name: '安装所需环境' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '核对原操作' }));
  await waitFor(() => expect(native.reconcile).toHaveBeenCalledWith('original-update'));
  expect(native.write).not.toHaveBeenCalled();
});

test('unknown preparation allows plain route confirmation but cannot grant a replacement installation', async () => {
  manifest.demands = [{ id: 'unknown-demand', requirement: flask, status: 'blocked_unknown' }];
  await open();
  expect((screen.getByRole('button', { name: '确认路线并安装' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '仅确认路线' }));
  await waitFor(() => expect(native.navigate).toHaveBeenCalledOnce());
  expect(native.write.mock.calls[0][1]).toEqual({ expected_revision: 1 });
});
