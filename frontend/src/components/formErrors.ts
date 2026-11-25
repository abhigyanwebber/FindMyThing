import { ApiError } from "../api/client";

export interface FormFailure {
  /** Banner text for the whole form. */
  readonly message: string;
  /** Messages keyed by the form fields this form renders. */
  readonly fields: Readonly<Record<string, readonly string[]>>;
}

/**
 * Split a failed request into per-field messages (for fields the form shows) and a banner message.
 * Field errors for keys the form does not render are folded into the banner so nothing is silently dropped.
 */
export function toFormFailure(error: unknown, knownFields: readonly string[]): FormFailure {
  if (!(error instanceof ApiError)) {
    return { message: "Something went wrong. Please try again.", fields: {} };
  }
  const fields: Record<string, readonly string[]> = {};
  const extra: string[] = [];
  for (const [key, messages] of Object.entries(error.fieldErrors)) {
    if (knownFields.includes(key)) fields[key] = messages;
    else extra.push(...messages);
  }
  if (Object.keys(fields).length > 0) {
    return { message: extra.length > 0 ? extra.join(" ") : "Please correct the highlighted fields.", fields };
  }
  const reference = error.requestId ? ` (reference ${error.requestId})` : "";
  return { message: `${[error.message, ...extra].join(" ")}${error.status >= 500 ? reference : ""}`, fields };
}

/** Accept only same-site absolute paths as a post-sign-in destination (no open redirect). */
export function safeRedirectPath(value: unknown): string {
  if (typeof value !== "string") return "/";
  if (!value.startsWith("/") || value.startsWith("//") || value.includes("\\") || hasControlChar(value)) return "/";
  if (value === "/sign-in" || value === "/register") return "/";
  return value;
}

function hasControlChar(value: string): boolean {
  for (let i = 0; i < value.length; i += 1) {
    if (value.charCodeAt(i) < 0x20) return true;
  }
  return false;
}
