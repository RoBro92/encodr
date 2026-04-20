import type { AuthTokens } from "../types/api";

export class ApiError extends Error {
  status: number;
  details: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export class ApiUnauthorisedError extends ApiError {
  constructor(message = "Your session has expired. Please sign in again.", details?: unknown) {
    super(message, 401, details);
    this.name = "ApiUnauthorisedError";
  }
}

type SessionGetter = () => AuthTokens | null;
type SessionUpdater = (tokens: AuthTokens) => Promise<void> | void;
type SessionClearer = () => Promise<void> | void;

type RequestOptions = {
  auth?: boolean;
  retryOnUnauthorised?: boolean;
};

export class ApiClient {
  private readonly baseUrl: string;
  private readonly getTokens: SessionGetter;
  private readonly updateTokens: SessionUpdater;
  private readonly clearSession: SessionClearer;
  private refreshPromise: Promise<AuthTokens> | null = null;

  constructor({
    baseUrl,
    getTokens,
    updateTokens,
    clearSession,
  }: {
    baseUrl: string;
    getTokens: SessionGetter;
    updateTokens: SessionUpdater;
    clearSession: SessionClearer;
  }) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.getTokens = getTokens;
    this.updateTokens = updateTokens;
    this.clearSession = clearSession;
  }

  async request<T>(
    path: string,
    init: RequestInit = {},
    options: RequestOptions = {},
  ): Promise<T> {
    const { auth = true, retryOnUnauthorised = true } = options;
    const headers = new Headers(init.headers);
    if (!headers.has("Content-Type") && init.body) {
      headers.set("Content-Type", "application/json");
    }

    if (auth) {
      const tokens = this.getTokens();
      if (!tokens) {
        throw new ApiUnauthorisedError();
      }
      headers.set("Authorization", `Bearer ${tokens.access_token}`);
    }

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers,
    });

    if (response.status === 401 && auth && retryOnUnauthorised) {
      const refreshed = await this.refreshTokens();
      const retryHeaders = new Headers(init.headers);
      if (!retryHeaders.has("Content-Type") && init.body) {
        retryHeaders.set("Content-Type", "application/json");
      }
      retryHeaders.set("Authorization", `Bearer ${refreshed.access_token}`);
      const retryResponse = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: retryHeaders,
      });
      return this.parseResponse<T>(retryResponse);
    }

    return this.parseResponse<T>(response);
  }

  private async parseResponse<T>(response: Response): Promise<T> {
    if (response.status === 204) {
      return undefined as T;
    }

    const contentType = response.headers.get("content-type") ?? "";
    const body = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      const message =
        typeof body === "object" && body !== null && "detail" in body
          ? String((body as { detail: unknown }).detail)
          : response.statusText || "Request failed.";

      if (response.status === 401) {
        await this.clearSession();
        throw new ApiUnauthorisedError(message, body);
      }

      throw new ApiError(message, response.status, body);
    }

    return body as T;
  }

  private async refreshTokens(): Promise<AuthTokens> {
    const current = this.getTokens();
    if (!current?.refresh_token) {
      await this.clearSession();
      throw new ApiUnauthorisedError();
    }

    if (!this.refreshPromise) {
      this.refreshPromise = fetch(`${this.baseUrl}/auth/refresh`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ refresh_token: current.refresh_token }),
      })
        .then(async (response) => {
          const parsed = await this.parseResponse<AuthTokens>(response);
          await this.updateTokens(parsed);
          return parsed;
        })
        .finally(() => {
          this.refreshPromise = null;
        });
    }

    return this.refreshPromise;
  }
}
