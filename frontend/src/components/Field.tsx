import type { ChangeEvent } from "react";
import styles from "./Form.module.css";

interface FieldProps {
  readonly id: string;
  readonly label: string;
  readonly type: "text" | "email" | "password";
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly autoComplete: string;
  readonly errors?: readonly string[] | undefined;
  readonly hint?: string;
  readonly maxLength?: number;
}

/** Labelled text input with programmatically associated hint and error text (WCAG 2.1 AA, contract section 14). */
export default function Field({ id, label, type, value, onChange, autoComplete, errors, hint, maxLength }: FieldProps) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const hasError = errors !== undefined && errors.length > 0;
  const describedBy = [hint ? hintId : null, hasError ? errorId : null].filter(Boolean).join(" ");
  return (
    <div className={styles["field"]}>
      <label htmlFor={id}>{label}</label>
      {hint ? (
        <span id={hintId} className={styles["hint"]}>
          {hint}
        </span>
      ) : null}
      <input
        id={id}
        name={id}
        type={type}
        value={value}
        autoComplete={autoComplete}
        required
        {...(maxLength !== undefined ? { maxLength } : {})}
        aria-invalid={hasError}
        {...(describedBy ? { "aria-describedby": describedBy } : {})}
        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
      />
      {hasError ? (
        <span id={errorId} className={styles["error"]}>
          {errors.join(" ")}
        </span>
      ) : null}
    </div>
  );
}
