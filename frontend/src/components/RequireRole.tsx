import { Navigate, Outlet, useLocation } from "react-router-dom";
import type { Role } from "../api/auth";
import { useAuth } from "../context/auth-context";

/**
 * Presentation-only route guard. The backend re-checks authentication and role on every request; this only keeps
 * the wrong audience from seeing screens that would just answer 401/403.
 */
export default function RequireRole({ role }: { role?: Role }) {
  const { state, retry } = useAuth();
  const location = useLocation();
  if (state.status === "loading") return <p role="status">Checking your session…</p>;
  if (state.status === "error") {
    return (
      <div>
        <p role="alert">{state.message}</p>
        <button type="button" onClick={retry}>
          Try again
        </button>
      </div>
    );
  }
  if (state.status === "anonymous") {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname + location.search }} />;
  }
  if (role && state.user.role !== role) {
    return (
      <>
        <h1>Not available</h1>
        <p>This page is not available for your account.</p>
      </>
    );
  }
  return <Outlet />;
}
