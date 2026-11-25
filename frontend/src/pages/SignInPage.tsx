import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import Field from "../components/Field";
import styles from "../components/Form.module.css";
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
      <p>
        New here? <Link to="/register">Create an account</Link>
      </p>
    </>
  );
}
