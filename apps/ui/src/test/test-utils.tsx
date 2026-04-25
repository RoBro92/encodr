import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import App from "../App";
import { AppProviders } from "../app/AppProviders";
import type { StoredSession } from "../lib/auth/storage";

const CURRENT_VERSION = __ENCODR_VERSION__;

export function renderApp({
  route = "/",
  initialSession = null,
}: {
  route?: string;
  initialSession?: StoredSession | null;
}) {
  return render(
    <AppProviders initialSession={initialSession} hydrateFromStorage={false}>
      <MemoryRouter initialEntries={[route]}>
        <App />
      </MemoryRouter>
    </AppProviders>,
  );
}

type MockRoute = {
  method?: string;
  path: string | RegExp;
  status?: number;
  body?: unknown;
};

export function mockFetchRoutes(routes: MockRoute[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = typeof input === "string" ? input : input.toString();
    const route = routes.find((candidate) => {
      const methodMatches = (candidate.method ?? "GET").toUpperCase() === method;
      if (!methodMatches) {
        return false;
      }
      if (typeof candidate.path === "string") {
        return url.includes(candidate.path);
      }
      return candidate.path.test(url);
    });

    if (!route && method === "GET" && url.includes("/api/auth/bootstrap-status")) {
      return new Response(
        JSON.stringify({
          bootstrap_allowed: false,
          first_user_setup_required: false,
          user_count: 1,
          version: CURRENT_VERSION,
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        },
      );
    }

    if (!route && method === "GET" && url.includes("/api/system/update")) {
      return new Response(
        JSON.stringify({
          current_version: CURRENT_VERSION,
          latest_version: null,
          update_available: false,
          channel: "internal",
          status: "disabled",
          release_name: null,
          release_summary: null,
          checked_at: null,
          error: null,
          download_url: null,
          release_notes_url: null,
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        },
      );
    }

    if (!route && method === "GET" && url.includes("/api/jobs/progress-stream")) {
      return new Response("", {
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
        },
      });
    }

    if (!route) {
      throw new Error(`Unhandled fetch request: ${method} ${url}`);
    }

    return new Response(JSON.stringify(route.body ?? {}), {
      status: route.status ?? 200,
      headers: {
        "Content-Type": "application/json",
      },
    });
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function makeSession(): StoredSession {
  return {
    tokens: {
      access_token: "access-token",
      refresh_token: "refresh-token",
      token_type: "bearer",
      access_token_expires_in: 1800,
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
}

export function resetBrowserState() {
  if (typeof window.localStorage.clear === "function") {
    window.localStorage.clear();
  }
  vi.unstubAllGlobals();
}
