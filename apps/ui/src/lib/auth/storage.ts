import type { AuthTokens, CurrentUser } from "../types/api";

export type StoredSession = {
  tokens: AuthTokens;
  user: CurrentUser;
};

export const SESSION_STORAGE_KEY = "encodr.session";

export function loadStoredSession(): StoredSession | null {
  const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (!raw) {
    const legacyRaw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!legacyRaw) {
      return null;
    }
    try {
      const migrated = JSON.parse(legacyRaw) as StoredSession;
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(migrated));
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
      return migrated;
    } catch {
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
      return null;
    }
  }
  try {
    return JSON.parse(raw) as StoredSession;
  } catch {
    window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
    return null;
  }
}

export function saveStoredSession(session: StoredSession): void {
  window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  window.localStorage.removeItem(SESSION_STORAGE_KEY);
}

export function clearStoredSession(): void {
  window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  window.localStorage.removeItem(SESSION_STORAGE_KEY);
}
