import { useCallback, useState } from "react";
import { listActivity, type ActivityItem } from "../../api/data";
import styles from "../../components/Page.module.css";
import { fmtDate, LoadGate, Pager, StatusBadge } from "../../components/ui";
import { useLoad } from "../../useLoad";
import { usePageTitle } from "../../usePageTitle";

const PAGE_SIZE = 25;

/** Moderator security and audit activity log feed (`GET /moderation/activity`). */
export default function ModeratorActivityPage() {
  usePageTitle("Moderation: Activity Feed");
  const [page, setPage] = useState(1);

  const load = useCallback(
    (signal: AbortSignal) => listActivity(page, signal),
    [page],
  );
  const results = useLoad(load);

  return (
    <>
      <h1>System activity &amp; audit feed</h1>
      <p>Tamper-evident log of report changes, claim transitions, evidence updates, and moderation actions.</p>

      <LoadGate loading={results.loading} error={results.error} onRetry={results.reload}>
        {results.data && results.data.items.length === 0 ? (
          <p>No activity recorded yet.</p>
        ) : null}

        <div className={styles["tableWrap"]}>
          <table className={styles["table"]}>
            <caption className="sr-only">Platform activity log</caption>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Event</th>
                <th scope="col">Target</th>
                <th scope="col">Actor</th>
                <th scope="col">Outcome</th>
                <th scope="col">Details</th>
              </tr>
            </thead>
            <tbody>
              {results.data?.items.map((item: ActivityItem) => (
                <tr key={item.activity_id}>
                  <td>{fmtDate(item.created_at_utc)}</td>
                  <td>
                    <strong>{item.event_type.replace(/_/g, " ")}</strong>
                  </td>
                  <td>
                    {item.target_type}
                    {item.target_id ? (
                      <span className={styles["metaBlock"]}>
                        {item.target_id.slice(0, 8)}…
                      </span>
                    ) : null}
                  </td>
                  <td>{item.actor ? item.actor.display_name : "System / Background"}</td>
                  <td>
                    <StatusBadge status={item.outcome} />
                  </td>
                  <td>
                    {item.metadata && Object.keys(item.metadata).length > 0 ? (
                      <pre>
                        {JSON.stringify(item.metadata, null, 2)}
                      </pre>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {results.data ? (
          <Pager
            page={page}
            pageSize={results.data.page_size || PAGE_SIZE}
            total={results.data.total}
            onPage={setPage}
          />
        ) : null}
      </LoadGate>
    </>
  );
}
