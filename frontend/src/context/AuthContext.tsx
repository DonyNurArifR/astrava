import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { AUTH_REQUIRED_EVENT, clearCsrfToken, setCsrfToken } from '../api/session';
import { AuthContext, type AuthContextType } from './auth-types';

/**
 * Tracks the operator session. The operator key is never stored here: it is passed to
 * `login` once and discarded by the caller. Only the server-issued CSRF token is kept, in
 * module memory, via the API client.
 */
export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [status, setStatus] = useState<'checking' | 'ready'>('checking');
  const [loginRequired, setLoginRequired] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [actorId, setActorId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Promise.resolve().then keeps a synchronous failure (e.g. a partial API mock) on the
    // promise path, so it is handled below instead of crashing the tree.
    Promise.resolve()
      .then(() => api.getSession())
      .then(session => {
        if (cancelled) return;
        setLoginRequired(session.login_required);
        setAuthenticated(session.authenticated);
        setActorId(session.actor_id);
        if (session.authenticated && session.csrf_token) {
          setCsrfToken(session.csrf_token);
        }
      })
      .catch(() => {
        // Session lookup unavailable: render the app as before. Any protected call that
        // returns 401 dispatches AUTH_REQUIRED_EVENT, which moves the UI to sign-in.
        if (cancelled) return;
        setLoginRequired(false);
        setAuthenticated(false);
      })
      .finally(() => {
        if (!cancelled) setStatus('ready');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onAuthRequired = () => {
      // A 401 proves the server requires sign-in, even if the initial session lookup failed.
      clearCsrfToken();
      setLoginRequired(true);
      setAuthenticated(false);
    };
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
  }, []);

  const login = useCallback(async (apiKey: string) => {
    const session = await api.login(apiKey);
    setCsrfToken(session.csrf_token);
    setLoginRequired(true);
    setAuthenticated(true);
    setActorId(session.actor_id);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Clear local state even if the server call fails; the session cookie expires anyway.
    } finally {
      clearCsrfToken();
      setAuthenticated(false);
    }
  }, []);

  const value: AuthContextType = {
    status,
    loginRequired,
    authenticated,
    actorId,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
