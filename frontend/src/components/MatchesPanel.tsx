import { useCallback } from "react";
import { Link } from "react-router-dom";
import { dismissMatch, listMatches, recalculateMatches, type MatchItem } from "../api/data";
import { useLoad } from "../useLoad";
import ActionForm from "./ActionForm";
import styles from "./Page.module.css";
import { LoadGate, StatusBadge } from "./ui";
import { useState } from "react";
import { toFormFailure } from "./formErrors";
import { Alert, Notice } from "./ui";

const DISMISS_REASONS = [
  { value: "INVALID_MATCH", label: "Not a real match" },
  { value: "DUPLICATE_MATCH", label: "Duplicate" },
  { value: "OTHER", label: "Other (note required)" },
] as const;

function factorSummary(match: MatchItem): string | null {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(match.factors)) {
    if (typeof value === "number" || typeof value === "string") parts.push(`${key.replace(/_/g, " ")}: ${value}`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** Potential matches for one report (owner or moderator; the backend decides what each role sees). */
export default function MatchesPanel({ reportId, moderator, canRecalculate }: { reportId: string; moderator: boolean; canRecalculate: boolean }) {
  const load = useCallback((signal: AbortSignal) => listMatches(reportId, signal), [reportId]);
  const matches = useLoad(load);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function recalculate() {
    setError(null);
    setNotice(null);
    try {
      await recalculateMatches(reportId);
      setNotice("Matching was requested. Refresh in a moment to see updated suggestions.");
    } catch (e) {
      setError(toFormFailure(e, []).message);
    }
  }

  return (
    <section aria-labelledby="matches-heading">
      <h2 id="matches-heading">Possible matches</h2>
      {error ? <Alert>{error}</Alert> : null}
      {notice ? <Notice>{notice}</Notice> : null}
      <LoadGate loading={matches.loading} error={matches.error} onRetry={matches.reload}>
        {matches.data && matches.data.items.length === 0 ? <p>No possible matches yet.</p> : null}
        <ul className={styles["cards"]}>
          {matches.data?.items.map((m) => {
            const summary = factorSummary(m);
            return (
              <li key={m.match_id} className={styles["card"]}>
                <h3>
                  <Link to={`/reports/${m.counterpart_report.report_id}`}>{m.counterpart_report.title}</Link>
                </h3>
                <p className={styles["meta"]}>
                  Score {m.score} · {m.counterpart_report.category_name} · {m.counterpart_report.location_name} ·{" "}
                  {m.counterpart_report.occurred_on} {moderator ? <StatusBadge status={m.match_status} /> : null}
                </p>
                {summary ? <p className={styles["meta"]}>{summary}</p> : null}
                {moderator && m.match_status === "POTENTIAL" ? (
                  <ActionForm
                    title="Dismiss this match"
                    submitLabel="Dismiss match"
                    reasons={DISMISS_REASONS}
                    noteLabel="Note"
                    onSubmit={async ({ reason, note }) => {
                      await dismissMatch(m.match_id, reason, note || undefined);
                      matches.reload();
                    }}
                  />
                ) : null}
              </li>
            );
          })}
        </ul>
      </LoadGate>
      {canRecalculate ? (
        <button type="button" className={styles["secondary"]} onClick={recalculate}>
          Refresh matches
        </button>
      ) : null}
    </section>
  );
}
