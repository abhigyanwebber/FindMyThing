/** Local development API (backend/.env.example: API_PUBLIC_ORIGIN=http://localhost:8000; routes live under /api). */
export const LOCAL_API_BASE_URL = "http://localhost:8000/api";

/**
 * Validate and normalise the build-time API base URL.
 *
 * - Unset: the local API in development; an error in production builds (no silent guessing).
 * - Production must be https. Plain http is accepted only in development.
 * - Credentials, query strings and fragments are rejected: nothing secret belongs in a public bundle.
 * - The result never ends with a slash, so callers append paths that start with "/".
 */
export function resolveApiBaseUrl(raw: string | undefined, isDev: boolean): string {
  const value = (raw ?? "").trim();
  if (value === "") {
    if (isDev) return LOCAL_API_BASE_URL;
    throw new Error("VITE_API_BASE_URL is not set. Set it to the API base URL, e.g. https://api.example.edu/api.");
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("VITE_API_BASE_URL is not a valid absolute URL.");
  }
  if (url.protocol !== "https:" && !(isDev && url.protocol === "http:")) {
    throw new Error("VITE_API_BASE_URL must use https (http is allowed only for local development).");
  }
  if (url.username !== "" || url.password !== "") {
    throw new Error("VITE_API_BASE_URL must not embed credentials.");
  }
  if (url.search !== "" || url.hash !== "") {
    throw new Error("VITE_API_BASE_URL must not contain a query string or fragment.");
  }
  return `${url.origin}${url.pathname}`.replace(/\/+$/, "");
}

/** The configured API base URL. Throws a descriptive error when the build is misconfigured. */
export function getApiBaseUrl(): string {
  return resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL, import.meta.env.DEV);
}
