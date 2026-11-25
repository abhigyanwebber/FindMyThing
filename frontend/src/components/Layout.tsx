import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/auth-context";
import styles from "./Layout.module.css";

/** Application shell: skip link, banner/nav/main/footer landmarks, and focus moved to <main> on route change. */
export default function Layout() {
  const { pathname } = useLocation();
  const { state, signOut } = useAuth();
  const navigate = useNavigate();
  const mainRef = useRef<HTMLElement>(null);
  const firstRender = useRef(true);
  const [signOutError, setSignOutError] = useState<string | null>(null);

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    mainRef.current?.focus();
  }, [pathname]);

  async function onSignOut() {
    setSignOutError(null);
    try {
      await signOut();
      navigate("/");
    } catch {
      setSignOutError("Could not sign out. Check your connection and try again.");
    }
  }

  const user = state.status === "authenticated" ? state.user : null;

  return (
    <div className={styles["shell"]}>
      <a className={styles["skipLink"]} href="#main">
        Skip to main content
      </a>
      <header className={styles["header"]}>
        <NavLink to="/" className={styles["brand"] ?? ""}>
          FindMyThing
        </NavLink>
        <nav aria-label="Primary" className={styles["nav"]}>
          <NavLink to="/" end>
            Home
          </NavLink>
          {user?.role === "STUDENT" ? (
            <>
              <NavLink to="/reports" end>
                Browse
              </NavLink>
              <NavLink to="/reports/new">Report</NavLink>
              <NavLink to="/my/reports">My reports</NavLink>
              <NavLink to="/my/claims">My claims</NavLink>
            </>
          ) : null}
          {user?.role === "MODERATOR" ? (
            <>
              <NavLink to="/reports" end>
                Browse
              </NavLink>
              <NavLink to="/moderator" end>
                Claims
              </NavLink>
              <NavLink to="/moderator/analytics">Analytics</NavLink>
              <NavLink to="/moderator/activity">Activity</NavLink>
            </>
          ) : null}
          {user ? (
            <button type="button" onClick={onSignOut}>
              Sign out ({user.display_name})
            </button>
          ) : state.status === "anonymous" ? (
            <>
              <NavLink to="/sign-in">Sign in</NavLink>
              <NavLink to="/register">Register</NavLink>
            </>
          ) : null}
        </nav>
      </header>
      <main id="main" ref={mainRef} tabIndex={-1} className={styles["main"]}>
        {signOutError ? <p role="alert">{signOutError}</p> : null}
        <Outlet />
      </main>
      <footer className={styles["footer"]}>Campus lost &amp; found and item recovery</footer>
    </div>
  );
}
