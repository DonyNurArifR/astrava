import { useContext } from 'react';
import { ThemeContext } from './theme-types';

export const useTheme = () => useContext(ThemeContext);
