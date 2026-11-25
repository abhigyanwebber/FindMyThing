import { useId, useState, type FormEvent } from "react";
import { toFormFailure } from "./formErrors";
import styles from "./Page.module.css";
import { Alert } from "./ui";

export interface ReasonOption {
  readonly value: string;
  readonly label: string;
}

export interface ActionValues {
  readonly reason: string;
  readonly note: string;
}

interface ActionFormProps {
  /** Heading shown on the disclosure and used to name the form. */
  readonly title: string;
  readonly submitLabel: string;
  readonly reasons?: readonly ReasonOption[];
  readonly noteLabel?: string;
  readonly noteRequired?: boolean;
  readonly noteMin?: number;
  readonly noteMax?: number;
  readonly danger?: boolean;
  readonly onSubmit: (values: ActionValues) => Promise<void>;
}

/**
 * A collapsed reason + note form for one moderator/owner action. Client checks only give early feedback;
 * the backend validates every field and its message is shown verbatim when it disagrees.
 */
export default function ActionForm({
  title,
  submitLabel,
  reasons,
  noteLabel = "Note",
  noteRequired = false,
  noteMin = 0,
  noteMax = 1000,
  danger = false,
  onSubmit,
}: ActionFormProps) {
  const uid = useId();
  const [reason, setReason] = useState(reasons?.[0]?.value ?? "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = note.trim();
    if (noteRequired && trimmed.length === 0) {
      setError(`${noteLabel} is required.`);
      return;
    }
    if (trimmed.length > 0 && trimmed.length < noteMin) {
      setError(`${noteLabel} must be at least ${noteMin} characters.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ reason, note: trimmed });
      setNote("");
    } catch (e) {
      setError(toFormFailure(e, []).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className={styles["action"]}>
      <summary>{title}</summary>
      <form onSubmit={submit} aria-label={title} className={styles["stack"]}>
        {error ? <Alert>{error}</Alert> : null}
        {reasons ? (
          <label htmlFor={`${uid}-reason`}>
            Reason
            <select id={`${uid}-reason`} value={reason} onChange={(e) => setReason(e.target.value)}>
              {reasons.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label htmlFor={`${uid}-note`}>
          {noteLabel}
          {noteRequired ? "" : " (optional)"}
          <textarea id={`${uid}-note`} rows={3} maxLength={noteMax} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <button type="submit" className={danger ? styles["danger"] ?? "" : styles["secondary"] ?? ""} disabled={busy}>
          {busy ? "Working…" : submitLabel}
        </button>
      </form>
    </details>
  );
}
