import { ApiError } from './client';

/** User-facing message for a failed operator sign-in. */
export function describeLoginError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return 'That operator key was not accepted.';
    if (err.status === 429) {
      return err.retryAfterSeconds !== null
        ? `Too many failed attempts. Try again in ${err.retryAfterSeconds} seconds.`
        : 'Too many failed attempts. Try again later.';
    }
    if (err.status === 409) return 'Sign-in is not required in this environment.';
  }
  return 'Sign-in failed. Check that the server is running and try again.';
}
