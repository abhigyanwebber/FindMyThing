import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiRequest, apiRequestNoContent, setCsrfToken } from "./client";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

function lastCall(): { url: string; init: RequestInit; headers: Headers } {
  const call = fetchMock.mock.calls.at(-1);
  if (call === undefined) throw new Error("fetch was not called");
  const init = call[1] ?? {};
  return { url: String(call[0]), init, headers: new Headers(init.headers) };
}

beforeEach(() => {
  vi.stubEnv("VITE_API_BASE_URL", "http://localhost:8000/api");
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  setCsrfToken(null);
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("API transport: session and CSRF design", () => {
  it("sends the session cookie on every request and never an Authorization header (no JWT)", async () => {
    // A fresh Response per call: a Response body can only be read once.
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({ ok: true })));
    setCsrfToken("csrf-123");
    await apiRequest("/reports");
    await apiRequest("/reports", { method: "POST", json: {} });
    for (const call of fetchMock.mock.calls) {
      const init = call[1] ?? {};
      expect(init.credentials).toBe("include");
      expect(new Headers(init.headers).has("Authorization")).toBe(false);
    }
  });

  it("targets the configured API base and prefixes API-relative paths", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    await apiRequest("/reports?page=1");
    expect(lastCall().url).toBe("http://localhost:8000/api/reports?page=1");
  });

  it.each(["POST", "PUT", "PATCH", "DELETE"] as const)("attaches X-CSRF-Token on %s", async (method) => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    setCsrfToken("csrf-abc");
    await apiRequest("/x", { method, json: {} });
    expect(lastCall().headers.get("X-CSRF-Token")).toBe("csrf-abc");
  });

  it("does not attach the CSRF token to GET requests", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    setCsrfToken("csrf-abc");
    await apiRequest("/x");
    expect(lastCall().headers.has("X-CSRF-Token")).toBe(false);
  });

  it("holds the CSRF token in memory only: web storage is never written", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    fetchMock.mockResolvedValue(jsonResponse({}));
    setCsrfToken("csrf-secret");
    await apiRequest("/x", { method: "POST", json: { password: "never-stored" } });
    expect(setItem).not.toHaveBeenCalled();
    expect(document.cookie).not.toContain("csrf-secret");
  });

  it("stops sending the token once it is cleared (logout)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    setCsrfToken("csrf-abc");
    setCsrfToken(null);
    await apiRequest("/x", { method: "POST", json: {} });
    expect(lastCall().headers.has("X-CSRF-Token")).toBe(false);
  });

  it("never caches API responses", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    await apiRequest("/x");
    expect(lastCall().init.cache).toBe("no-store");
  });
});

describe("API transport: request building", () => {
  it.each(["https://evil.example/steal", "//evil.example/x", "reports", "/a://b"])("refuses a path that could leave the API: %s", async (path) => {
    await expect(apiRequest(path)).rejects.toThrow(TypeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("serialises JSON bodies with a JSON content type", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    await apiRequest("/x", { method: "POST", json: { a: 1 } });
    const { init, headers } = lastCall();
    expect(init.body).toBe('{"a":1}');
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("lets the browser set the multipart boundary for uploads", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    const form = new FormData();
    form.append("file", new Blob(["x"], { type: "image/png" }), "a.png");
    await apiRequest("/reports/1/photo", { method: "POST", form });
    const { init, headers } = lastCall();
    expect(init.body).toBe(form);
    expect(headers.has("Content-Type")).toBe(false);
  });

  it("rejects a request that supplies both json and form", async () => {
    await expect(apiRequest("/x", { method: "POST", json: {}, form: new FormData() })).rejects.toThrow(TypeError);
  });

  it("supports 204 No Content endpoints", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiRequestNoContent("/auth/logout", { method: "POST", json: {} })).resolves.toBeUndefined();
  });
});

describe("API transport: errors", () => {
  it("parses the contract error envelope including field errors and request id", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { error: { code: "VALIDATION_ERROR", message: "Invalid email.", field_errors: { email: ["Enter a valid email address."] } } },
        422,
        { "X-Request-ID": "req-9" },
      ),
    );
    const error = await apiRequest("/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const api = error as ApiError;
    expect([api.status, api.code, api.message, api.requestId]).toEqual([422, "VALIDATION_ERROR", "Invalid email.", "req-9"]);
    expect(api.fieldErrors["email"]).toEqual(["Enter a valid email address."]);
  });

  it("uses the request_id from the error body when the header is absent", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: { code: "FORBIDDEN", message: "No.", request_id: "body-req-1" } }, 403));
    const api = (await apiRequest("/x").catch((e: unknown) => e)) as ApiError;
    expect([api.status, api.code, api.requestId]).toEqual([403, "FORBIDDEN", "body-req-1"]);
  });

  it("reports a misconfigured API base as a configuration error, not a network error", async () => {
    vi.stubEnv("DEV", false); // production build semantics: plain http is refused
    vi.stubEnv("VITE_API_BASE_URL", "http://api.example.edu/api");
    const error = await apiRequest("/x").catch((e: unknown) => e);
    expect(error).not.toBeInstanceOf(ApiError);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toMatch(/https/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("falls back to a generic message for a non-JSON error body", async () => {
    fetchMock.mockResolvedValue(new Response("<html>Bad gateway</html>", { status: 502 }));
    const api = (await apiRequest("/x").catch((e: unknown) => e)) as ApiError;
    expect(api).toBeInstanceOf(ApiError);
    expect([api.status, api.code]).toEqual([502, "HTTP_ERROR"]);
    expect(api.message).not.toContain("Bad gateway");
  });

  it("maps a network failure to NETWORK_ERROR without leaking details", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch: https://internal.example/secret"));
    const api = (await apiRequest("/x").catch((e: unknown) => e)) as ApiError;
    expect([api.status, api.code]).toEqual([0, "NETWORK_ERROR"]);
    expect(api.message).not.toContain("internal.example");
  });

  it("propagates an aborted request unchanged", async () => {
    fetchMock.mockRejectedValue(new DOMException("aborted", "AbortError"));
    await expect(apiRequest("/x")).rejects.toMatchObject({ name: "AbortError" });
  });
});
