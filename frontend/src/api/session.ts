/** Window event dispatched when a protected request returns 401 (session missing or expired). */
export const AUTH_REQUIRED_EVENT = 'astrava:auth-required';

// The CSRF token lives only in module memory: never in localStorage, sessionStorage or a cookie.
let csrfToken: string | null = null;

export function setCsrfToken(token: string): void {
  csrfToken = token;
}

export function clearCsrfToken(): void {
  csrfToken = null;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}
