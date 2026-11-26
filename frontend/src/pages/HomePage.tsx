import { Link } from "react-router-dom";
import { useAuth } from "../context/auth-context";
import styles from "../components/Page.module.css";
import { usePageTitle } from "../usePageTitle";

interface Tile {
  readonly to: string;
  readonly title: string;
  readonly text: string;
}

const STUDENT_TILES: readonly Tile[] = [
  { to: "/reports", title: "Browse lost & found", text: "Search reports from across campus." },
  { to: "/reports/new", title: "Report lost or found item", text: "File a report in under a minute." },
  { to: "/my/reports", title: "View my reports", text: "Withdrawn and closed reports." },
  { to: "/my/claims", title: "View my claims", text: "Track claims and add evidence." },
];

const MODERATOR_TILES: readonly Tile[] = [
  { to: "/moderator", title: "Review pending claims", text: "Verify proof and supervise handovers." },
  { to: "/reports", title: "Browse all reports", text: "Every report, with moderation tools." },
  { to: "/moderator/analytics", title: "Campus analytics", text: "Recovery rates and trends." },
  { to: "/moderator/activity", title: "System activity log", text: "Audit feed of every action." },
];

const ANONYMOUS_TILES: readonly Tile[] = [
  { to: "/reports", title: "Browse found items", text: "See what has been handed in." },
  { to: "/sign-in", title: "Sign in", text: "Use your campus account." },
  { to: "/register", title: "Create account", text: "Register to report and claim." },
];

const STEPS: readonly Tile[] = [
  { to: "", title: "1. Report", text: "Describe what you lost or found, with an optional photo." },
  { to: "", title: "2. Match", text: "Reports are compared automatically and likely matches are flagged." },
  { to: "", title: "3. Verify & recover", text: "Claims are checked by a moderator, then the item is handed over in person." },
];

function TileList({ tiles }: { tiles: readonly Tile[] }) {
  return (
    <ul className={styles["tiles"]}>
      {tiles.map((t) => (
        <li key={t.to}>
          <Link to={t.to} className={styles["tile"]}>
            <span className={styles["tileTitle"]}>{t.title}</span>
            <span className={styles["tileText"]}>{t.text}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default function HomePage() {
  usePageTitle(null);
  const { state } = useAuth();
  const user = state.status === "authenticated" ? state.user : null;

  return (
    <>
      <div className={styles["hero"]}>
        <h1>Campus lost &amp; found</h1>
        <p>
          FindMyThing helps students and campus moderators reunite lost items with their owners
          securely, with tamper-evident audit logs and multi-factor matching.
        </p>
      </div>

      {user ? (
        <section aria-labelledby="welcome-heading">
          <p className={styles["rubric"]}>{user.role === "MODERATOR" ? "Moderator desk" : "Student desk"}</p>
          <h2 id="welcome-heading" className={styles["flushTop"]}>
            Welcome back, {user.display_name}!
          </h2>
          <p>
            You are signed in as a <strong>{user.role}</strong>.
          </p>
          <TileList tiles={user.role === "MODERATOR" ? MODERATOR_TILES : STUDENT_TILES} />
        </section>
      ) : (
        <>
          <section aria-labelledby="get-started-heading">
            <p className={styles["rubric"]}>Start here</p>
            <h2 id="get-started-heading" className={styles["flushTop"]}>
              Get started
            </h2>
            <p>Sign in with your campus account or register to report lost items and submit claims.</p>
            <TileList tiles={ANONYMOUS_TILES} />
          </section>
          <section aria-labelledby="how-heading">
            <p className={styles["rubricSpaced"]}>
              The process
            </p>
            <h2 id="how-heading" className={styles["flushTop"]}>
              How it works
            </h2>
            <ol className={styles["tiles"]}>
              {STEPS.map((s) => (
                <li key={s.title} className={styles["tile"]}>
                  <span className={styles["tileTitle"]}>{s.title}</span>
                  <span className={styles["tileText"]}>{s.text}</span>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
    </>
  );
}
