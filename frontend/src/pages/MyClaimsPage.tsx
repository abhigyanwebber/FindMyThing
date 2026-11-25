import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { listMyClaims } from "../api/data";
import styles from "../components/Page.module.css";
import { fmtDate, LoadGate, Pager, StatusBadge } from "../components/ui";
import { useLoad } from "../useLoad";
import { usePageTitle } from "../usePageTitle";

/** The signed-in student's claims (`GET /me/claims`). */
export default function MyClaimsPage() {
  usePageTitle("My claims");
  const [page, setPage] = useState(1);
  const load = useCallback((signal: AbortSignal) => listMyClaims(page, signal), [page]);
  const results = useLoad(load);

  return (
    <>
      <h1>My claims</h1>
      <LoadGate loading={results.loading} error={results.error} onRetry={results.reload}>
        {results.data && results.data.items.length === 0 ? (
          <p>
            You have not made any claims. Find an item in <Link to="/reports?type=FOUND">found reports</Link>.
          </p>
        ) : null}
        <ul className={styles["cards"]}>
          {results.data?.items.map((c) => (
            <li key={c.claim_id} className={styles["card"]}>
              <h2>
                <Link to={`/my/claims/${c.claim_id}`}>{c.found_report.title}</Link>
              </h2>
              <p className={styles["meta"]}>
                <StatusBadge status={c.status} /> · submitted {fmtDate(c.created_at_utc)}
              </p>
              {c.information_request.note ? <p>A moderator asked for more information.</p> : null}
            </li>
          ))}
        </ul>
        {results.data ? <Pager page={page} pageSize={results.data.page_size || 20} total={results.data.total} onPage={setPage} /> : null}
      </LoadGate>
    </>
  );
}
