import { describe, expect, it } from "vitest";
import { LOCAL_API_BASE_URL, resolveApiBaseUrl } from "./config";

describe("resolveApiBaseUrl", () => {
  it("defaults to the local API in development when unset or blank", () => {
    expect(resolveApiBaseUrl(undefined, true)).toBe(LOCAL_API_BASE_URL);
    expect(resolveApiBaseUrl("   ", true)).toBe(LOCAL_API_BASE_URL);
  });

  it("refuses to guess in a production build", () => {
    expect(() => resolveApiBaseUrl(undefined, false)).toThrow(/VITE_API_BASE_URL is not set/);
  });

  it("accepts https in production and strips trailing slashes", () => {
    expect(resolveApiBaseUrl("https://api.example.edu/api/", false)).toBe("https://api.example.edu/api");
    expect(resolveApiBaseUrl("https://api.example.edu/api///", false)).toBe("https://api.example.edu/api");
  });

  it("allows plain http only for local development", () => {
    expect(resolveApiBaseUrl("http://localhost:8000/api", true)).toBe("http://localhost:8000/api");
    expect(() => resolveApiBaseUrl("http://api.example.edu/api", false)).toThrow(/https/);
  });

  it("rejects malformed values, credentials, queries and fragments", () => {
    expect(() => resolveApiBaseUrl("not a url", true)).toThrow(/valid absolute URL/);
    expect(() => resolveApiBaseUrl("https://user:secret@api.example.edu/api", false)).toThrow(/credentials/);
    expect(() => resolveApiBaseUrl("https://api.example.edu/api?key=1", false)).toThrow(/query string/);
    expect(() => resolveApiBaseUrl("https://api.example.edu/api#frag", false)).toThrow(/query string or fragment/);
  });
});
