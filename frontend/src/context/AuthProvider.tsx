import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { login, logout, register as registerAccount, restoreSession } from "../api/auth";
import { ApiError } from "../api/client";
import { AuthContext, type AuthContextValue, type AuthState } from "./auth-context";

/** Loads the session once on mount (`GET /auth/me` + `GET /auth/csrf`) and exposes sign-in/register/sign-out. */
export default function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    restoreSession(controller.signal)
      .then((user) => {
        if (controller.signal.aborted) return;
        setState(user === null ? { status: "anonymous" } : { status: "authenticated", user });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message = error instanceof ApiError ? error.message : "Could not check your session.";
        setState({ status: "error", message });
      });
    return () => controller.abort();
  }, [attempt]);

  const signIn = useCallback(async (email: string, password: string) => {
    const user = await login(email, password);
    setState({ status: "authenticated", user });
    return user;
  }, []);

  const register = useCallback(async (displayName: string, email: string, password: string) => {
    const user = await registerAccount(displayName, email, password);
    setState({ status: "authenticated", user });
    return user;
  }, []);

  const signOut = useCallback(async () => {
    await logout();
    setState({ status: "anonymous" });
  }, []);

  const retry = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((n) => n + 1);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ state, signIn, register, signOut, retry }),
    [state, signIn, register, signOut, retry],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
