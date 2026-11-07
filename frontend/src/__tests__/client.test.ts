import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import clientSource from '../api/client.ts?raw';
import { api, ApiError } from '../api/client';
import { AUTH_REQUIRED_EVENT, clearCsrfToken, setCsrfToken } from '../api/session';

const IDENTITY_KEYS = ['decided_by', 'actor_id', 'verified_by'];

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

function lastCall(fetchMock: ReturnType<typeof vi.fn>): [string, RequestInit] {
  const call = fetchMock.mock.calls.at(-1);
  if (!call) throw new Error('fetch was not called');
  return call as [string, RequestInit];
}

describe('API client request wrapper', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // A fresh Response per call: a Response body can only be read once.
    fetchMock = vi.fn(async () => jsonResponse(200, []));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    clearCsrfToken();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('sends same-origin credentials on every request', async () => {
    await api.getProjects();
    const [, init] = lastCall(fetchMock);
    expect(init.credentials).toBe('same-origin');
  });

  it('does not send X-CSRF-Token on GET, even when a token is set', async () => {
    setCsrfToken('csrf-token-value');
    await api.getProjects();
    const [url, init] = lastCall(fetchMock);
    expect(url).toBe('/api/v1/projects');
    expect(init.method).toBe('GET');
    expect(new Headers(init.headers).has('X-CSRF-Token')).toBe(false);
  });

  it('sends X-CSRF-Token on POST once a token is set', async () => {
    setCsrfToken('csrf-token-value');
    await api.createProject({ name: 'P', studio_type: 'saas' as never });
    const [, init] = lastCall(fetchMock);
    expect(init.method).toBe('POST');
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-token-value');
  });

  it('sends X-CSRF-Token on PATCH and DELETE too', async () => {
    setCsrfToken('csrf-token-value');
    await api.updateAgentStatus('agent-slug', true);
    expect(new Headers(lastCall(fetchMock)[1].headers).get('X-CSRF-Token')).toBe('csrf-token-value');
    await api.deleteProject('p-1');
    expect(new Headers(lastCall(fetchMock)[1].headers).get('X-CSRF-Token')).toBe('csrf-token-value');
  });

  it('stops sending X-CSRF-Token after clearCsrfToken', async () => {
    setCsrfToken('csrf-token-value');
    clearCsrfToken();
    await api.pauseExecution('e-1');
    expect(new Headers(lastCall(fetchMock)[1].headers).has('X-CSRF-Token')).toBe(false);
  });

  it('dispatches astrava:auth-required on 401 and then throws the server detail', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { detail: 'Missing or invalid operator credentials' })
    );
    const listener = vi.fn();
    window.addEventListener(AUTH_REQUIRED_EVENT, listener);
    try {
      await expect(api.getProjects()).rejects.toThrow('Missing or invalid operator credentials');
      expect(listener).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(AUTH_REQUIRED_EVENT, listener);
    }
  });

  it('does not dispatch auth-required for a wrong key on the login endpoint', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: 'Invalid operator credentials' }));
    const listener = vi.fn();
    window.addEventListener(AUTH_REQUIRED_EVENT, listener);
    try {
      await expect(api.login('wrong-key')).rejects.toBeInstanceOf(ApiError);
      expect(listener).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener(AUTH_REQUIRED_EVENT, listener);
    }
  });

  it('keeps the previous error message format and exposes status and Retry-After', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(429, { detail: 'Too many failed login attempts' }, { 'Retry-After': '42' })
    );
    const error = await api.login('k').catch(e => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe('Too many failed login attempts');
    expect(error.status).toBe(429);
    expect(error.retryAfterSeconds).toBe(42);
  });

  it('posts the operator key only as a JSON body to the login endpoint', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        authenticated: true,
        auth_method: 'session',
        actor_id: 'Abstract',
        csrf_token: 'csrf-from-login',
        expires_at: '2030-01-01T00:00:00Z',
      })
    );
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const result = await api.login('secret-operator-key-value');
    const [url, init] = lastCall(fetchMock);
    expect(url).toBe('/api/v1/auth/login');
    expect(init.method).toBe('POST');
    expect(init.body).toBe(JSON.stringify({ api_key: 'secret-operator-key-value' }));
    expect(url).not.toContain('secret-operator-key-value');
    expect(result.csrf_token).toBe('csrf-from-login');
    expect(setItem).not.toHaveBeenCalled();
  });

  it('exposes getSession and logout against the session endpoints', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        authenticated: false,
        auth_method: null,
        login_required: true,
        actor_id: null,
        csrf_token: null,
      })
    );
    const session = await api.getSession();
    expect(session.login_required).toBe(true);
    expect(lastCall(fetchMock)[0]).toBe('/api/v1/auth/session');

    fetchMock.mockResolvedValueOnce(jsonResponse(200, { authenticated: false }));
    await api.logout();
    expect(lastCall(fetchMock)[0]).toBe('/api/v1/auth/logout');
    expect(lastCall(fetchMock)[1].method).toBe('POST');
  });

  describe('request bodies never carry identity fields', () => {
    function expectNoIdentity(init: RequestInit) {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      for (const key of IDENTITY_KEYS) {
        expect(body).not.toHaveProperty(key);
      }
      expect(new Headers(init.headers).has('X-ASTRAVA-ACTOR-NAME')).toBe(false);
    }

    it('decideApproval', async () => {
      await api.decideApproval('appr-1', 'approved', 'Looks good');
      expect(JSON.parse(String(lastCall(fetchMock)[1].body))).toEqual({
        decision: 'approved',
        reason: 'Looks good',
      });
      expectNoIdentity(lastCall(fetchMock)[1]);
    });

    it('resumePipeline', async () => {
      await api.resumePipeline('exec-1', 'rejected', 'No');
      expectNoIdentity(lastCall(fetchMock)[1]);
    });

    it('verifyMemory ignores any identity a caller passes in', async () => {
      await api.verifyMemory('proj-1', 'mem-1', {
        reason: 'Reviewed',
        verified_by: 'Tech Lead',
        actor_id: 'someone',
      } as never);
      expect(JSON.parse(String(lastCall(fetchMock)[1].body))).toEqual({
        reason: 'Reviewed',
        verification_details: undefined,
      });
      expectNoIdentity(lastCall(fetchMock)[1]);
    });

    it('resolveConflict ignores any identity a caller passes in', async () => {
      await api.resolveConflict('proj-1', 'mem-1', {
        resolution: 'reject',
        reason: 'Duplicate',
        actor_id: 'someone',
      } as never);
      expectNoIdentity(lastCall(fetchMock)[1]);
    });
  });

  it('routes every call through the single request wrapper (no raw fetch elsewhere)', () => {
    const fetchCalls = clientSource.match(/\bfetch\(/g) ?? [];
    expect(fetchCalls).toHaveLength(1);
    expect(clientSource).not.toMatch(/decided_by|actor_id|verified_by|ACTOR-NAME/);
  });
});
