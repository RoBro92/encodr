import {
  type PropsWithChildren,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ApiClient, ApiUnauthorisedError } from "../../lib/api/client";
import { getCurrentUser, login as loginRequest, logout as logoutRequest } from "../../lib/api/endpoints";
import {
  clearStoredSession,
  loadStoredSession,
  saveStoredSession,
  type StoredSession,
} from "../../lib/auth/storage";
import type { AuthTokens, CurrentUser } from "../../lib/types/api";

type SessionContextValue = {
  apiClient: ApiClient;
  user: CurrentUser | null;
  tokens: AuthTokens | null;
  ready: boolean;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  clearSession: () => Promise<void>;
};

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

type AuthProviderProps = PropsWithChildren<{
  initialSession?: StoredSession | null;
  hydrateFromStorage?: boolean;
  apiBaseUrl?: string;
}>;

export function AuthProvider({
  children,
  initialSession,
  hydrateFromStorage = true,
  apiBaseUrl = "/api",
}: AuthProviderProps) {
  const [tokens, setTokens] = useState<AuthTokens | null>(initialSession?.tokens ?? null);
  const [user, setUser] = useState<CurrentUser | null>(initialSession?.user ?? null);
  const [ready, setReady] = useState<boolean>(Boolean(initialSession) || !hydrateFromStorage);
  const sessionRef = useRef<StoredSession | null>(initialSession ?? null);

  const persistSession = useCallback(async (nextTokens: AuthTokens, nextUser?: CurrentUser | null) => {
    const effectiveUser = nextUser ?? sessionRef.current?.user ?? null;
    if (!effectiveUser) {
      return;
    }

    const nextSession: StoredSession = { tokens: nextTokens, user: effectiveUser };
    sessionRef.current = nextSession;
    setTokens(nextTokens);
    setUser(effectiveUser);
    saveStoredSession(nextSession);
  }, []);

  const clearSession = useCallback(async () => {
    sessionRef.current = null;
    setTokens(null);
    setUser(null);
    clearStoredSession();
    setReady(true);
  }, []);

  const apiClient = useMemo(
    () =>
      new ApiClient({
        baseUrl: apiBaseUrl,
        getTokens: () => sessionRef.current?.tokens ?? null,
        updateTokens: async (nextTokens) => {
          await persistSession(nextTokens);
        },
        clearSession,
      }),
    [apiBaseUrl, clearSession, persistSession],
  );

  const completeSession = useCallback(
    async (nextTokens: AuthTokens) => {
      const bootstrapClient = new ApiClient({
        baseUrl: apiBaseUrl,
        getTokens: () => nextTokens,
        updateTokens: async () => undefined,
        clearSession,
      });
      const nextUser = await getCurrentUser(bootstrapClient);
      sessionRef.current = { tokens: nextTokens, user: nextUser };
      setTokens(nextTokens);
      setUser(nextUser);
      saveStoredSession({ tokens: nextTokens, user: nextUser });
      setReady(true);
    },
    [apiBaseUrl, clearSession],
  );

  useEffect(() => {
    if (!hydrateFromStorage || initialSession) {
      setReady(true);
      return;
    }

    const stored = loadStoredSession();
    if (!stored) {
      setReady(true);
      return;
    }

    sessionRef.current = stored;
    setTokens(stored.tokens);
    setUser(stored.user);

    getCurrentUser(apiClient)
      .then((resolvedUser) => {
        sessionRef.current = { tokens: stored.tokens, user: resolvedUser };
        setUser(resolvedUser);
        saveStoredSession({ tokens: stored.tokens, user: resolvedUser });
      })
      .catch(async () => {
        await clearSession();
      })
      .finally(() => {
        setReady(true);
      });
  }, [apiClient, clearSession, hydrateFromStorage, initialSession]);

  const login = useCallback(
    async (username: string, password: string) => {
      const nextTokens = await loginRequest(apiClient, { username, password });
      await completeSession(nextTokens);
    },
    [apiClient, completeSession],
  );

  const logout = useCallback(async () => {
    try {
      if (sessionRef.current?.tokens) {
        await logoutRequest(apiClient);
      }
    } catch (error) {
      if (!(error instanceof ApiUnauthorisedError)) {
        // Intentionally ignored to avoid trapping the operator in a stale session.
      }
    } finally {
      await clearSession();
    }
  }, [apiClient, clearSession]);

  const value = useMemo<SessionContextValue>(
    () => ({
      apiClient,
      user,
      tokens,
      ready,
      isAuthenticated: Boolean(tokens && user),
      login,
      logout,
      clearSession,
    }),
    [apiClient, clearSession, login, logout, ready, tokens, user],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession must be used within an AuthProvider.");
  }
  return context;
}
