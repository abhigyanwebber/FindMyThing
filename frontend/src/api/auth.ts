/**
 * Typed auth endpoints (contract 4.1). The session is an HttpOnly cookie managed by the browser and the backend;
 * the only credential this module handles is the CSRF token, which is kept in memory by `client.ts`.
 */
import { ApiError, apiRequest, apiRequestNoContent, setCsrfToken } from "./client";

export type Role = "STUDENT" | "MODERATOR";

/** `{user_id, display_name, email, role}` exactly as returned by login/register/me. No password or session fields. */
export interface User {
  readonly user_id: string;
  readonly display_name: string;
  readonly email: string;
  readonly role: Role;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function invalidResponse(): ApiError {
  return new ApiError(0, "INVALID_RESPONSE", "The server sent an unexpected response.");
}

function parseUser(value: unknown): User {
  if (!isRecord(value)) throw invalidResponse();
  const { user_id, display_name, email, role } = value;
  if (
    typeof user_id !== "string" ||
    typeof display_name !== "string" ||
    typeof email !== "string" ||
    (role !== "STUDENT" && role !== "MODERATOR")
  ) {
    throw invalidResponse();
  }
  return { user_id, display_name, email, role };
}

function parseSession(value: unknown): { user: User; csrfToken: string } {
  if (!isRecord(value) || typeof value["csrf_token"] !== "string" || value["csrf_token"] === "") throw invalidResponse();
  return { user: parseUser(value["user"]), csrfToken: value["csrf_token"] };
}

export async function login(email: string, password: string, signal?: AbortSignal): Promise<User> {
  const data = await apiRequest<unknown>("/auth/login", {
    method: "POST",
    json: { email, password },
    ...(signal ? { signal } : {}),
  });
  const session = parseSession(data);
  setCsrfToken(session.csrfToken);
  return session.user;
}

export async function register(displayName: string, email: string, password: string, signal?: AbortSignal): Promise<User> {
  const data = await apiRequest<unknown>("/auth/register", {
    method: "POST",
    json: { display_name: displayName, email, password },
    ...(signal ? { signal } : {}),
  });
  const session = parseSession(data);
  setCsrfToken(session.csrfToken);
  return session.user;
}

/** Fetch a fresh CSRF token for the current session (required after a page reload; contract 4.1). */
export async function refreshCsrf(signal?: AbortSignal): Promise<void> {
  const data = await apiRequest<unknown>("/auth/csrf", signal ? { signal } : {});
  if (!isRecord(data) || typeof data["csrf_token"] !== "string" || data["csrf_token"] === "") throw invalidResponse();
  setCsrfToken(data["csrf_token"]);
}

/**
 * Restore the session after a page load: `GET /auth/me`, then `GET /auth/csrf`.
 * Resolves to `null` when there is no valid session (HTTP 401). Any other failure is thrown.
 */
export async function restoreSession(signal?: AbortSignal): Promise<User | null> {
  try {
    const data = await apiRequest<unknown>("/auth/me", signal ? { signal } : {});
    if (!isRecord(data)) throw invalidResponse();
    const user = parseUser(data["user"]);
    await refreshCsrf(signal);
    return user;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      setCsrfToken(null);
      return null;
    }
    throw error;
  }
}

async function postLogout(): Promise<void> {
  try {
    await apiRequestNoContent("/auth/logout", { method: "POST" });
  } catch (error) {
    if (error instanceof ApiError && error.code === "CSRF_INVALID") {
      await refreshCsrf();
      await apiRequestNoContent("/auth/logout", { method: "POST" });
      return;
    }
    throw error;
  }
}

/**
 * Revoke the session. A stale CSRF token (CSRF_INVALID) is refreshed once and retried. A 401 means the session is
 * already gone, which is the outcome the caller wanted. The in-memory CSRF token is dropped once the session is gone;
 * on any other failure (e.g. network) it is kept so the user can retry.
 */
export async function logout(): Promise<void> {
  try {
    await postLogout();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      setCsrfToken(null);
      return;
    }
    throw error;
  }
  setCsrfToken(null);
}