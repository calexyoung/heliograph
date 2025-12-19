import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import type { User, AuthTokens, LoginRequest, RegisterRequest } from '../types';

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (credentials: LoginRequest) => Promise<void>;
  register: (data: RegisterRequest) => Promise<void>;
  logout: () => void;
  getAccessToken: () => string | null;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const TOKEN_KEY = 'heliograph_tokens';
const USER_KEY = 'heliograph_user';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [tokens, setTokens] = useState<AuthTokens | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Load stored auth data on mount
  useEffect(() => {
    const storedTokens = localStorage.getItem(TOKEN_KEY);
    const storedUser = localStorage.getItem(USER_KEY);

    if (storedTokens && storedUser) {
      try {
        setTokens(JSON.parse(storedTokens));
        setUser(JSON.parse(storedUser));
      } catch {
        // Invalid stored data, clear it
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
      }
    }
    setIsLoading(false);
  }, []);

  const saveAuth = useCallback((authTokens: AuthTokens, authUser: User) => {
    setTokens(authTokens);
    setUser(authUser);
    localStorage.setItem(TOKEN_KEY, JSON.stringify(authTokens));
    localStorage.setItem(USER_KEY, JSON.stringify(authUser));
  }, []);

  const clearAuth = useCallback(() => {
    setTokens(null);
    setUser(null);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }, []);

  const login = useCallback(async (credentials: LoginRequest) => {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(credentials),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Login failed');
    }

    const authTokens: AuthTokens = await response.json();

    // Fetch user info
    const userResponse = await fetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${authTokens.access_token}` },
    });

    if (!userResponse.ok) {
      throw new Error('Failed to fetch user info');
    }

    const authUser: User = await userResponse.json();
    saveAuth(authTokens, authUser);
  }, [saveAuth]);

  const register = useCallback(async (data: RegisterRequest) => {
    const response = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Registration failed');
    }

    const authTokens: AuthTokens = await response.json();

    // Fetch user info
    const userResponse = await fetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${authTokens.access_token}` },
    });

    if (!userResponse.ok) {
      throw new Error('Failed to fetch user info');
    }

    const authUser: User = await userResponse.json();
    saveAuth(authTokens, authUser);
  }, [saveAuth]);

  const logout = useCallback(async () => {
    if (tokens?.access_token) {
      try {
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: { Authorization: `Bearer ${tokens.access_token}` },
        });
      } catch {
        // Ignore logout errors
      }
    }
    clearAuth();
  }, [tokens, clearAuth]);

  const getAccessToken = useCallback(() => {
    return tokens?.access_token || null;
  }, [tokens]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        register,
        logout,
        getAccessToken,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
