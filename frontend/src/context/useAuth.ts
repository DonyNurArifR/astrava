import { useContext } from 'react';
import { AuthContext } from './auth-types';

export const useAuth = () => useContext(AuthContext);
