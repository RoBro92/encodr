import { afterEach, describe, expect, it } from "vitest";

import {
  SESSION_STORAGE_KEY,
  clearStoredSession,
  loadStoredSession,
  saveStoredSession,
  type StoredSession,
} from "./storage";

const session: StoredSession = {
  tokens: {
    access_token: "access-token",
    refresh_token: "refresh-token",
    token_type: "bearer",
    access_token_expires_in: 900,
    refresh_token_expires_in: 1209600,
  },
  user: {
    id: "user-1",
    username: "admin",
    role: "admin",
    is_active: true,
    is_bootstrap_admin: true,
    last_login_at: null,
  },
};

describe("auth session storage", () => {
  afterEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("stores auth sessions in sessionStorage", () => {
    saveStoredSession(session);

    expect(window.sessionStorage.getItem(SESSION_STORAGE_KEY)).toContain("access-token");
    expect(window.localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(loadStoredSession()).toEqual(session);
  });

  it("migrates and clears legacy localStorage sessions", () => {
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));

    expect(loadStoredSession()).toEqual(session);
    expect(window.localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(SESSION_STORAGE_KEY)).toContain("refresh-token");
  });

  it("clears both current and legacy auth storage", () => {
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));

    clearStoredSession();

    expect(window.localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });
});
