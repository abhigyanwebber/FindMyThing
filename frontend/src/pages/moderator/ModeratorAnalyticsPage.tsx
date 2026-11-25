import { useCallback, useState } from "react";
import { getAnalytics, type Analytics } from "../../api/data";
import styles from "../../components/Page.module.css";
import { LoadGate } from "../../components/ui";
import { useLoad } from "../../useLoad";
import { usePageTitle } from "../../usePageTitle";

function isoDate(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Moderator analytics dashboard (`GET /moderation/analytics/summary`). */
export default function ModeratorAnalyticsPage() {
  usePageTitle("Moderation: Analytics");
  const [dateFrom, setDateFrom] = useState(isoDate(-90));
  const [dateTo, setDateTo] = useState(isoDate(0));
  const [applied, setApplied] = useState({ from: isoDate(-90), to: isoDate(0) });

  const load = useCallback(
    (signal: AbortSignal) => getAnalytics(applied.from, applied.to, signal),
    [applied],
  );
  const result = useLoad(load);
  const data: Analytics | null = result.data;

  function onFilter(e: React.FormEvent) {
    e.preventDefault();
    setApplied({ from: dateFrom, to: dateTo });
  }

  return (
    <>
      <h1>Campus recovery analytics</h1>
      <p>Performance metrics, recovery rates, category trends, and recovery time analysis.</p>

      <form className={styles["filters"]} onSubmit={onFilter}>
        <label>
          From date
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </label>
        <label>
          To date
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </label>
        <button type="submit" className={styles["secondary"] ?? ""}>
          Update range
        </button>
      </form>

      <LoadGate loading={result.loading} error={result.error} onRetry={result.reload}>
        {data ? (
          <div className={styles["stack"]} style={{ maxWidth: "100%" }}>
            <section aria-labelledby="kpi-heading">
              <h2 id="kpi-heading">Key metrics ({data.period.from} to {data.period.to})</h2>
              <dl className={styles["dl"]}>
                <dt>Lost reports</dt>
                <dd>{data.lost_reports}</dd>
                <dt>Found reports</dt>
                <dd>{data.found_reports}</dd>
                <dt>Currently active reports</dt>
                <dd>{data.active_reports}</dd>
                <dt>Claims submitted</dt>
                <dd>{data.claims.submitted}</dd>
                <dt>Claims verified</dt>
                <dd>{data.claims.verified}</dd>
                <dt>Claims rejected</dt>
                <dd>{data.claims.rejected}</dd>
                <dt>Claims cancelled</dt>
                <dd>{data.claims.cancelled}</dd>
                <dt>Items recovered</dt>
                <dd>
                  <strong>{data.recoveries}</strong>
                </dd>
                <dt>Recovery rate</dt>
                <dd>
                  {data.recovery_rate_pct !== null ? `${data.recovery_rate_pct}%` : "—"}
                </dd>
                <dt>Recovery rate (excluding withdrawn)</dt>
                <dd>
                  {data.recovery_rate_non_withdrawn_pct !== null
                    ? `${data.recovery_rate_non_withdrawn_pct}%`
                    : "—"}
                </dd>
                <dt>Average recovery time</dt>
                <dd>
                  {data.average_recovery_days !== null
                    ? `${data.average_recovery_days} days`
                    : "—"}
                </dd>
                <dt>Median recovery time</dt>
                <dd>
                  {data.median_recovery_days !== null
                    ? `${data.median_recovery_days} days`
                    : "—"}
                </dd>
              </dl>
            </section>

            <section aria-labelledby="by-category-heading">
              <h2 id="by-category-heading">Breakdown by category</h2>
              <div className={styles["tableWrap"]}>
                <table className={styles["table"]}>
                  <caption className="sr-only">Report and recovery breakdown by category</caption>
                  <thead>
                    <tr>
                      <th scope="col">Category</th>
                      <th scope="col">Lost</th>
                      <th scope="col">Found</th>
                      <th scope="col">Recoveries</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_category.map((cat) => (
                      <tr key={cat.category_id}>
                        <td>{cat.name}</td>
                        <td>{cat.lost}</td>
                        <td>{cat.found}</td>
                        <td>{cat.recoveries}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section aria-labelledby="by-location-heading">
              <h2 id="by-location-heading">Breakdown by location</h2>
              <div className={styles["tableWrap"]}>
                <table className={styles["table"]}>
                  <caption className="sr-only">Report and recovery breakdown by location</caption>
                  <thead>
                    <tr>
                      <th scope="col">Location</th>
                      <th scope="col">Lost</th>
                      <th scope="col">Found</th>
                      <th scope="col">Recoveries</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_location.map((loc) => (
                      <tr key={loc.location_id}>
                        <td>{loc.name}</td>
                        <td>{loc.lost}</td>
                        <td>{loc.found}</td>
                        <td>{loc.recoveries}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {data.monthly && data.monthly.length > 0 ? (
              <section aria-labelledby="monthly-heading">
                <h2 id="monthly-heading">Monthly volume trends</h2>
                <div className={styles["tableWrap"]}>
                  <table className={styles["table"]}>
                    <caption className="sr-only">Monthly report and recovery volume trends</caption>
                    <thead>
                      <tr>
                        <th scope="col">Month</th>
                        <th scope="col">Lost</th>
                        <th scope="col">Found</th>
                        <th scope="col">Recoveries</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.monthly.map((m) => (
                        <tr key={m.month}>
                          <td>{m.month}</td>
                          <td>{m.lost}</td>
                          <td>{m.found}</td>
                          <td>{m.recoveries}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}
          </div>
        ) : null}
      </LoadGate>
    </>
  );
}
