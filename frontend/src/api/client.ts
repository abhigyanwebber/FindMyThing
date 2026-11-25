/**
 * Minimal API transport (Task 3.1 foundation; the auth context and typed endpoints arrive in Task 3.2).
 *
 * Security rules enforced here (contract 4.1, ARCHITECTURE):
 * - Server-side session cookie only: every request is sent with `credentials: "include"`. No JWT, no Authorization header.
 * - The CSRF token lives in module memory only. It is never written to localStorage/sessionStorage/cookies.
 * - `X-CSRF-Token` is attached to POST/PUT/PATCH/DELETE. The browser supplies `Origin`; the backend authorises.
 * - Paths must be API-relative ("/reports"). Absolute URLs are refused so a request can never be pointed elsewhere.
 */
import { getApiBaseUrl } from "../config";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

const UNSAFE_METHODS: ReadonlySet<HttpMethod> = new Set<HttpMethod>(["POST", "PUT", "PATCH", "DELETE"]);

let csrfToken: string | null = null;

/** Store the CSRF token returned by login/register/`GET /auth/csrf` (memory only). */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Common error envelope (contract 1): `{ error: { code, message, request_id, field_errors? } }`. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly fieldErrors: Readonly<Record<string, readonly string[]>>;

  constructor(
    status: number,
    code: string,
    message: string,
    requestId: string | null = null,
    fieldErrors: Readonly<Record<string, readonly string[]>> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.fieldErrors = fieldErrors;
  }
}

export interface RequestOptions {
  method?: HttpMethod;
  /** JSON request body. Mutually exclusive with `form`. */
  json?: unknown;
  /** Multipart body (photo/evidence uploads). The browser sets the multipart boundary. */
  form?: FormData;
  signal?: AbortSignal;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function toApiError(response: Response): Promise<ApiError> {
  let requestId = response.headers.get("X-Request-ID");
  let code = "HTTP_ERROR";
  let message = `The request failed (HTTP ${response.status}).`;
  const fieldErrors: Record<string, string[]> = {};
  try {
    const data: unknown = await response.json();
    if (isRecord(data) && isRecord(data["error"])) {
      const error = data["error"];
      if (typeof error["code"] === "string") code = error["code"];
      if (typeof error["message"] === "string") message = error["message"];
      // Contract 1: the body carries the same request_id as the X-Request-ID header; use it if the header is absent.
      if (requestId === null && typeof error["request_id"] === "string") requestId = error["request_id"];
      const fields = error["field_errors"];
      if (isRecord(fields)) {
        for (const [field, messages] of Object.entries(fields)) {
          if (Array.isArray(messages)) fieldErrors[field] = messages.filter((m): m is string => typeof m === "string");
        }
      }
    }
  } catch {
    // Non-JSON error body: keep the generic message.
  }
  return new ApiError(response.status, code, message, requestId, fieldErrors);
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("://")) {
    throw new TypeError("API paths must be relative to the API base and start with a single '/'.");
  }
  if (options.json !== undefined && options.form !== undefined) {
    throw new TypeError("Provide either `json` or `form`, not both.");
  }
  const method = options.method ?? "GET";
  const headers = new Headers({ Accept: "application/json" });
  let body: BodyInit | null = null;
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  } else if (options.form !== undefined) {
    body = options.form;
  }
  if (UNSAFE_METHODS.has(method) && csrfToken !== null) {
    headers.set("X-CSRF-Token", csrfToken);
  }

  // Resolve the base URL outside the network try/catch: a misconfigured build must surface its own descriptive
  // error, not be reported to the user as a connectivity problem.
  const url = `${getApiBaseUrl()}${path}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body,
      credentials: "include",
      cache: "no-store",
      signal: options.signal ?? null,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "NETWORK_ERROR", "Could not reach the server. Check your connection and try again.");
  }
  if (!response.ok) throw await toApiError(response);
  return response;
}

/**
 * Request a JSON resource. The body is returned as `T` without runtime validation: callers in Task 3.2 narrow it.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options);
  return (await response.json()) as T;
}

/** Request an endpoint that answers 204 No Content (logout, attachment delete). */
export async function apiRequestNoContent(path: string, options: RequestOptions = {}): Promise<void> {
  await send(path, options);
}
