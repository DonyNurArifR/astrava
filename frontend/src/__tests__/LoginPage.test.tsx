import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LoginPage } from '../pages/LoginPage';
import { AuthContext, type AuthContextType } from '../context/auth-types';
import { ApiError } from '../api/client';

function renderWithLogin(login: AuthContextType['login']) {
  const value: AuthContextType = {
    status: 'ready',
    loginRequired: true,
    authenticated: false,
    actorId: null,
    login,
    logout: vi.fn().mockResolvedValue(undefined),
  };
  return render(
    <AuthContext.Provider value={value}>
      <LoginPage />
    </AuthContext.Provider>
  );
}

function keyInput(): HTMLInputElement {
  return screen.getByLabelText('Operator key') as HTMLInputElement;
}

describe('LoginPage', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders a password field that browsers may autofill as the current password', () => {
    renderWithLogin(vi.fn());
    const input = keyInput();
    expect(input).toHaveAttribute('type', 'password');
    expect(input).toHaveAttribute('autocomplete', 'current-password');
  });

  it('submits the key to login and clears the field', async () => {
    const login = vi.fn().mockResolvedValue(undefined);
    renderWithLogin(login);

    fireEvent.change(keyInput(), { target: { value: 'operator-key-123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => expect(login).toHaveBeenCalledWith('operator-key-123'));
    await waitFor(() => expect(keyInput().value).toBe(''));
  });

  it('never touches localStorage or sessionStorage while handling the key', async () => {
    const login = vi.fn().mockRejectedValue(new ApiError('Invalid operator credentials', 401));
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    renderWithLogin(login);

    fireEvent.change(keyInput(), { target: { value: 'operator-key-123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    await screen.findByRole('alert');
    expect(setItem).not.toHaveBeenCalled();
    expect(getItem).not.toHaveBeenCalled();
  });

  it('shows a clear message for a wrong key', async () => {
    const login = vi.fn().mockRejectedValue(new ApiError('Invalid operator credentials', 401));
    renderWithLogin(login);

    fireEvent.change(keyInput(), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('That operator key was not accepted.');
  });

  it('shows the retry delay when rate limited', async () => {
    const login = vi.fn().mockRejectedValue(
      new ApiError('Too many failed login attempts', 429, 30)
    );
    renderWithLogin(login);

    fireEvent.change(keyInput(), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Too many failed attempts. Try again in 30 seconds.'
    );
  });

  it('does not call login for an empty submission', async () => {
    const login = vi.fn();
    renderWithLogin(login);

    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Enter the operator key to continue.');
    expect(login).not.toHaveBeenCalled();
  });
});
