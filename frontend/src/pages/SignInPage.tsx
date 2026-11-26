import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import Field from "../components/Field";
import styles from "../components/Form.module.css";
import pageStyles from "../components/Page.module.css";
import { safeRedirectPath, toFormFailure, type FormFailure } from "../components/formErrors";
import { useAuth } from "../context/auth-context";
import { usePageTitle } from "../usePageTitle";

const FIELDS = ["email", "password"] as const;

export default function SignInPage() {
  usePageTitle("Sign in");
  const { state, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = safeRedirectPath((location.state as { from?: unknown } | null)?.from);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<FormFailure | null>(null);

  if (state.status === "authenticated" && !busy) return <Navigate to={from} replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      await signIn(email.trim(), password);
      navigate(from, { replace: true });
    } catch (error) {
      setFailure(toFormFailure(error, FIELDS));
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Sign in</h1>
      <div className={pageStyles["authLayout"]}>
        <div className={`${pageStyles["panel"]} ${pageStyles["panelAccent"]}`}>
          <form className={styles["form"]} onSubmit={onSubmit}>
            {failure ? (
              <p role="alert" className={styles["banner"]}>
                {failure.message}
              </p>
            ) : null}
            <Field id="email" label="Email" type="email" value={email} onChange={setEmail} autoComplete="username" errors={failure?.fields["email"]} />
            <Field id="password" label="Password" type="password" value={password} onChange={setPassword} autoComplete="current-password" errors={failure?.fields["password"]} />
            <button type="submit" className={styles["primary"]} disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
          <p className={pageStyles["formFoot"]}>
            New here? <Link to="/register">Create an account</Link>
          </p>
        </div>
        <aside className={pageStyles["aside"]} aria-label="About signing in">
          <h2>Why sign in?</h2>
          <ul>
            <li>Report lost or found items and follow their status.</li>
            <li>Submit claims with proof of ownership. Only moderators review your evidence.</li>
            <li>Your session uses a secure cookie. Sign out when using a shared computer.</li>
          </ul>
        </aside>
      </div>
    </>
  );
}
