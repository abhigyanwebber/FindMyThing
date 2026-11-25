import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { listReports, type ReportStatus } from "../api/data";
import styles from "../components/Page.module.css";
import { LoadGate, Pager, StatusBadge } from "../components/ui";
import { useLoad } from "../useLoad";
import { usePageTitle } from "../usePageTitle";

const PAGE_SIZE = 12;
const TABS: { status: ReportStatus; label: string }[] = [
  { status: "WITHDRAWN", label: "Withdrawn" },
  { status: "CLOSED", label: "Closed by a moderator" },
];

/**
 * Your own reports that are no longer public. The API only lists a student's own reports for the
 * WITHDRAWN and CLOSED statuses; active and resolved reports are reachable from Browse.
 */
export default function MyReportsPage() {
  usePageTitle("My reports");
  const [status, setStatus] = useState<ReportStatus>("WITHDRAWN");
  const [page, setPage] = useState(1);
  const load = useCallback((signal: AbortSignal) => listReports({ status, page, page_size: PAGE_SIZE }, signal), [status, page]);
  const results = useLoad(load);

  return (
    <>
      <h1>My reports</h1>
      <p>
        Your active reports appear in <Link to="/reports">Browse</Link>. This page lists your reports that are no longer public.
      </p>
      <div className={styles["tabs"]} role="group" aria-label="Report status">
        {TABS.map((t) => (
          <button
            key={t.status}
            type="button"
            className={styles["secondary"] ?? ""}
            aria-pressed={status === t.status}
            onClick={() => {
              setStatus(t.status);
              setPage(1);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <LoadGate loading={results.loading} error={results.error} onRetry={results.reload}>
        {results.data && results.data.items.length === 0 ? <p>You have no {status.toLowerCase()} reports.</p> : null}
        <ul className={styles["cards"]}>
          {results.data?.items.map((r) => (
            <li key={r.report_id} className={styles["card"]}>
              <h2>
                <Link to={`/reports/${r.report_id}`}>{r.title}</Link>
              </h2>
              <p className={styles["meta"]}>
                {r.report_type === "LOST" ? "Lost" : "Found"} · {r.category.name} · {r.location.name} · <StatusBadge status={r.status} />
              </p>
            </li>
          ))}
        </ul>
        {results.data ? <Pager page={page} pageSize={PAGE_SIZE} total={results.data.total} onPage={setPage} /> : null}
      </LoadGate>
    </>
  );
}
