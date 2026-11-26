import type { ReactNode } from "react";
import type { ApiError } from "../api/client";
import styles from "./Page.module.css";

export function Alert({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className={styles["alert"]}>
      {children}
    </p>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <p role="status" className={styles["notice"]}>
      {children}
    </p>
  );
}

/** Loading / error wrapper for a `useLoad` result. */
export function LoadGate({
  loading,
  error,
  onRetry,
  children,
}: {
  loading: boolean;
  error: ApiError | null;
  onRetry: () => void;
  children: ReactNode;
}) {
  if (loading) return <p role="status">Loading…</p>;
  if (error) {
    return (
      <div>
        <Alert>{error.message}</Alert>
        <button type="button" className={styles["secondary"]} onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }
  return <>{children}</>;
}

const BADGE_TONES: Readonly<Record<string, string>> = {
  // positive outcomes
  RESOLVED: "toneSuccess",
  RECOVERED: "toneSuccess",
  VERIFIED: "toneSuccess",
  SUCCESS: "toneSuccess",
  // needs attention
  PENDING: "toneWarning",
  // negative outcomes
  REJECTED: "toneError",
  CLOSED: "toneError",
  FAILURE: "toneError",
  DENIED: "toneError",
  // inactive / informational
  WITHDRAWN: "toneNeutral",
  CANCELLED: "toneNeutral",
  SYSTEM: "toneNeutral",
};

/** Status chip. The text is the raw status (also what assistive tech reads); the tone only adds colour. */
export function StatusBadge({ status }: { status: string }) {
  const tone = BADGE_TONES[status.toUpperCase()];
  const className = [styles["badge"], tone ? styles[tone] : undefined].filter(Boolean).join(" ");
  return <span className={className}>{status}</span>;
}

export function Pager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return (
    <nav aria-label="Pagination" className={styles["pager"]}>
      <button type="button" className={styles["secondary"]} disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span>
        Page {page} of {pages}
      </span>
      <button type="button" className={styles["secondary"]} disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </nav>
  );
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}
