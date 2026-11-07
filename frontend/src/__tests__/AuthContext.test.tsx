import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { api } from '../api/client';
import { AUTH_REQUIRED_EVENT, clearCsrfToken } from '../api/session';

vi.mock('../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    api: {
      getSession: vi.fn(),
      login: vi.fn(),
      logout: vi.fn().mockResolvedValue({ authenticated: false }),
      getHealth: vi.fn().mockResolvedValue({ status: 'healthy', database: 'connected' }),
      getApprovals: vi.fn().mockResolvedValue([]),
      getProjects: vi.fn().mockResolvedValue([]),
      getProjectStats: vi.fn().mockResolvedValue({
        total_projects: 0,
        saas_projects: 0,
        media_projects: 0,
        total_tasks: 0,
        completed_tasks: 0,
        total_executions: 0,
        total_artifacts: 0,
        pending_approvals: 0,
        total_cost_usd: 0,
      }),
      getUsageSummary: vi.fn().mockResolvedValue({
        total_cost_usd: 0,
        total_executions: 0,
        total_tokens: 0,
        avg_duration_ms: 0,
        recent_executions: [],
      }),
      getExecutions: vi.fn().mockResolvedValue([]),
      getArtifactsByProject: vi.fn().mockResolvedValue([]),
      getIntelligenceSummary: vi.fn().mockResolvedValue({
        total_cost_usd: 0,
        total_executions: 0,
        total_tokens: 0,
        avg_duration_ms: 0,
        recent_executions: [],
      }),
    },
  };
});

const mocked = vi.mocked(api);

const LOCAL_DEV = {
  authenticated: false,
  auth_method: 'local_dev' as const,
  login_required: false,
  actor_id: 'Abstract',
  csrf_token: null,
};
const KEYED_SIGNED_OUT = {
  authenticated: false,
  auth_method: null,
  login_required: true,
  actor_id: null,
  csrf_token: null,
};
const KEYED_SIGNED_IN = {
  authenticated: true,
  auth_method: 'session' as const,
  login_required: true,
  actor_id: 'Abstract',
  csrf_token: 'csrf-signed-in',
};

describe('AuthContext and sign-in gate', () => {
  beforeEach(() => {
    mocked.getSession.mockReset();
    mocked.login.mockReset();
    mocked.logout.mockClear();
  });

  afterEach(() => {
    clearCsrfToken();
    vi.clearAllMocks();
  });

  it('renders the application without a login in local development mode', async () => {
    mocked.getSession.mockResolvedValue(LOCAL_DEV);
    render(<App />);

    expect(await screen.findByText('Executive Overview')).toBeInTheDocument();
    expect(screen.queryByText('Operator sign-in')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
  });

  it('renders the sign-in screen instead of the app when keyed and signed out', async () => {
    mocked.getSession.mockResolvedValue(KEYED_SIGNED_OUT);
    render(<App />);

    expect(await screen.findByText('Operator sign-in')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('Executive Overview')).not.toBeInTheDocument());
  });

  it('signs in with the key, then shows the app and the sign-out control', async () => {
    mocked.getSession.mockResolvedValue(KEYED_SIGNED_OUT);
    mocked.login.mockResolvedValue({
      authenticated: true,
      auth_method: 'session',
      actor_id: 'Abstract',
      csrf_token: 'csrf-after-login',
      expires_at: '2030-01-01T00:00:00Z',
    });
    render(<App />);

    fireEvent.change(await screen.findByLabelText('Operator key'), {
      target: { value: 'operator-key-value' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(mocked.login).toHaveBeenCalledWith('operator-key-value');
    expect(await screen.findByText('Executive Overview')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('shows the sign-out control only when login is required', async () => {
    mocked.getSession.mockResolvedValue(KEYED_SIGNED_IN);
    render(<App />);

    expect(await screen.findByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('signs out and returns to the sign-in screen', async () => {
    mocked.getSession.mockResolvedValue(KEYED_SIGNED_IN);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }));

    expect(mocked.logout).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('Operator sign-in')).toBeInTheDocument();
  });

  it('returns to the sign-in screen when a protected request reports auth-required', async () => {
    mocked.getSession.mockResolvedValue(KEYED_SIGNED_IN);
    render(<App />);
    await screen.findByText('Executive Overview');

    act(() => {
      window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT));
    });

    expect(await screen.findByText('Operator sign-in')).toBeInTheDocument();
  });

  it('reaches the sign-in screen after a failed session lookup once a 401 arrives', async () => {
    mocked.getSession.mockRejectedValue(new Error('network down'));
    render(<App />);
    await screen.findByText('Executive Overview');

    act(() => {
      window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT));
    });

    expect(await screen.findByText('Operator sign-in')).toBeInTheDocument();
  });

  it('returns to the sign-in screen after login when a later 401 arrives', async () => {
    mocked.getSession.mockResolvedValue(KEYED_SIGNED_OUT);
    mocked.login.mockResolvedValue({
      authenticated: true,
      auth_method: 'session',
      actor_id: 'Abstract',
      csrf_token: 'csrf-after-login',
      expires_at: '2030-01-01T00:00:00Z',
    });
    render(<App />);

    fireEvent.change(await screen.findByLabelText('Operator key'), {
      target: { value: 'operator-key-value' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await screen.findByText('Executive Overview');

    act(() => {
      window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT));
    });

    expect(await screen.findByText('Operator sign-in')).toBeInTheDocument();
  });

  it('renders the app when the session lookup itself fails (protected calls will still gate)', async () => {
    mocked.getSession.mockRejectedValue(new Error('network down'));
    render(<App />);

    expect(await screen.findByText('Executive Overview')).toBeInTheDocument();
    expect(screen.queryByText('Operator sign-in')).not.toBeInTheDocument();
  });
});
