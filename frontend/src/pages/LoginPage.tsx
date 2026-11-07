import React, { useState } from 'react';
import { AlertTriangle, KeyRound } from 'lucide-react';
import { Logo } from '../components/Logo';
import { describeLoginError } from '../api/login-error';
import { useAuth } from '../context/useAuth';

/**
 * Operator sign-in. The key lives only in this component's state until submit; it is cleared
 * from the field before the request is made and is never written to any storage.
 */
export const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const [apiKey, setApiKey] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const submitted = apiKey;
    setApiKey('');
    if (!submitted.trim()) {
      setError('Enter the operator key to continue.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await login(submitted);
    } catch (err) {
      setError(describeLoginError(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-slate-50 dark:bg-slate-950 font-sans antialiased text-slate-900 dark:text-slate-100 p-6">
      <div className="w-full max-w-sm bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-8 shadow-xl space-y-6">
        <div className="flex justify-center">
          <Logo size={36} />
        </div>
        <div className="text-center space-y-1">
          <h1 className="text-lg font-bold">Operator sign-in</h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Enter the operator key for this ASTRAVA instance.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="operator-key"
              className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1"
            >
              Operator key
            </label>
            <div className="relative">
              <KeyRound size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                id="operator-key"
                name="operator-key"
                type="password"
                autoComplete="current-password"
                spellCheck={false}
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                disabled={submitting}
                className="w-full text-sm pl-9 pr-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 p-3 bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 rounded-lg text-xs"
            >
              <AlertTriangle size={14} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-60 text-white text-sm font-semibold transition-colors"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
};
