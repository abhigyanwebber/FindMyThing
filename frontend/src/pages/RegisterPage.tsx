import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import Field from "../components/Field";
import styles from "../components/Form.module.css";
import pageStyles from "../components/Page.module.css";
import { toFormFailure, type FormFailure } from "../components/formErrors";
import { useAuth } from "../context/auth-context";
import { usePageTitle } from "../usePageTitle";

const FIELDS = ["display_name", "email", "password"] as const;

export default function RegisterPage() {
  usePageTitle("Create account");
  const { state, register } = useAuth();
  const navigate = useNavigate();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<FormFailure | null>(null);

  if (state.status === "authenticated" && !busy) return <Navigate to="/" replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      await register(displayName.trim(), email.trim(), password);
      navigate("/", { replace: true });
    } catch (error) {
      setFailure(toFormFailure(error, FIELDS));
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Create account</h1>
      <div className={pageStyles["authLayout"]}>
        <div className={`${pageStyles["panel"]} ${pageStyles["panelAccent"]}`}>
      <form className={styles["form"]} onSubmit={onSubmit}>
        {failure ? (
          <p role="alert" className={styles["banner"]}>
            {failure.message}
          </p>
        ) : null}
        <Field id="display_name" label="Display name" type="text" value={displayName} onChange={setDisplayName} autoComplete="name" maxLength={80} errors={failure?.fields["display_name"]} />
        <Field id="email" label="Email" type="email" value={email} onChange={setEmail} autoComplete="email" maxLength={254} errors={failure?.fields["email"]} />
        <Field id="password" label="Password" type="password" value={password} onChange={setPassword} autoComplete="new-password" hint="12 to 128 characters." maxLength={128} errors={failure?.fields["password"]} />
        <button type="submit" className={styles["primary"]} disabled={busy}>
          {busy ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className={pageStyles["formFoot"]}>
        Already registered? <Link to="/sign-in">Sign in</Link>
      </p>
        </div>
        <aside className={pageStyles["aside"]} aria-label="About accounts">
          <h2>Your account</h2>
          <ul>
            <li>Use your campus email. Your display name appears on the reports you file.</li>
            <li>Choose a unique password of 12 to 128 characters.</li>
            <li>Reports and claims you submit stay linked to this account.</li>
          </ul>
        </aside>
      </div>
    </>
  );
}
