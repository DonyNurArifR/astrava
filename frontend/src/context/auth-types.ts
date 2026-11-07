import { createContext } from 'react';

export interface AuthContextType {
  /** 'checking' until the first session lookup settles. */
  status: 'checking' | 'ready';
  /** True when the server requires operator sign-in (keyed mode). False in local development. */
  loginRequired: boolean;
  authenticated: boolean;
  actorId: string | null;
  login: (apiKey: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextType>({
  status: 'ready',
  loginRequired: false,
  authenticated: false,
  actorId: null,
  login: async () => {},
  logout: async () => {},
});
