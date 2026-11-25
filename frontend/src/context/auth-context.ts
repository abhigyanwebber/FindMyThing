import { createContext, useContext } from "react";
import type { User } from "../api/auth";

/**
 * Session state held by the UI. It is presentation state only: the backend re-checks authentication, role,
 * ownership and CSRF on every request. Nothing here is persisted (no localStorage/sessionStorage).
 */
export type AuthState =
  | { readonly status: "loading" }
  | { readonly status: "anonymous" }
  | { readonly status: "authenticated"; readonly user: User }
  | { readonly status: "error"; readonly message: string };

export interface AuthContextValue {
  readonly state: AuthState;
  /** Resolves to the signed-in user; rejects with the ApiError from the backend (field errors included). */
  signIn(email: string, password: string): Promise<User>;
  register(displayName: string, email: string, password: string): Promise<User>;
  /** Revokes the session on the server. Rejects if that failed, so the UI never shows "signed out" falsely. */
  signOut(): Promise<void>;
  /** Re-run session restoration after a failure that was not a plain "not signed in". */
  retry(): void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) throw new Error("useAuth must be used inside <AuthProvider>.");
  return value;
}
