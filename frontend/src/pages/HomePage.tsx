import { Link } from "react-router-dom";
import { useAuth } from "../context/auth-context";
import styles from "../components/Page.module.css";
import { usePageTitle } from "../usePageTitle";

export default function HomePage() {
  usePageTitle(null);
  const { state } = useAuth();
  const user = state.status === "authenticated" ? state.user : null;

  return (
    <>
      <h1>Campus lost &amp; found</h1>
      <p>
        FindMyThing helps students and campus moderators reunite lost items with their owners
        securely, with tamper-evident audit logs and multi-factor matching.
      </p>

      {user ? (
        <section aria-labelledby="welcome-heading" style={{ marginTop: "var(--space-4)" }}>
          <h2 id="welcome-heading">Welcome back, {user.display_name}!</h2>
          <p>
            You are signed in as a <strong>{user.role}</strong>.
          </p>
          <div className={styles["actions"]}>
            {user.role === "STUDENT" ? (
              <>
                <Link to="/reports" className={styles["secondary"] ?? ""}>
                  Browse lost &amp; found
                </Link>
                <Link to="/reports/new" className={styles["secondary"] ?? ""}>
                  Report lost or found item
                </Link>
                <Link to="/my/reports" className={styles["secondary"] ?? ""}>
                  View my reports
                </Link>
                <Link to="/my/claims" className={styles["secondary"] ?? ""}>
                  View my claims
                </Link>
              </>
            ) : null}
            {user.role === "MODERATOR" ? (
              <>
                <Link to="/moderator" className={styles["secondary"] ?? ""}>
                  Review pending claims
                </Link>
                <Link to="/reports" className={styles["secondary"] ?? ""}>
                  Browse all reports
                </Link>
                <Link to="/moderator/analytics" className={styles["secondary"] ?? ""}>
                  Campus analytics
                </Link>
                <Link to="/moderator/activity" className={styles["secondary"] ?? ""}>
                  System activity log
                </Link>
              </>
            ) : null}
          </div>
        </section>
      ) : (
        <section aria-labelledby="get-started-heading" style={{ marginTop: "var(--space-4)" }}>
          <h2 id="get-started-heading">Get started</h2>
          <p>Sign in with your campus account or register to report lost items and submit claims.</p>
          <div className={styles["actions"]}>
            <Link to="/reports" className={styles["secondary"] ?? ""}>
              Browse found items
            </Link>
            <Link to="/sign-in" className={styles["secondary"] ?? ""}>
              Sign in
            </Link>
            <Link to="/register" className={styles["secondary"] ?? ""}>
              Create account
            </Link>
          </div>
        </section>
      )}
    </>
  );
}

