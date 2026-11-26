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

function Stat({ label, value, featured = false }: { label: string; value: string | number; featured?: boolean }) {
  return (
    <div className={featured ? `${styles["stat"]} ${styles["statFeatured"]}` : styles["stat"]}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

interface BreakdownRow {
  readonly id: string;
  readonly name: string;
  readonly lost: number;
  readonly found: number;
  readonly recoveries: number;
}

function BreakdownTable({ title, headingId, firstColumn, caption, rows }: {
  title: string;
  headingId: string;
  firstColumn: string;
  caption: string;
  rows: readonly BreakdownRow[];
}) {
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId}>{title}</h2>
      <div className={styles["tableWrap"]}>
        <table className={styles["table"]}>
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              <th scope="col">{firstColumn}</th>
              <th scope="col" className={styles["num"]}>Lost</th>
              <th scope="col" className={styles["num"]}>Found</th>
              <th scope="col" className={styles["num"]}>Recoveries</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.name}</td>
                <td className={styles["num"]}>{row.lost}</td>
                <td className={styles["num"]}>{row.found}</td>
                <td className={styles["num"]}>{row.recoveries}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
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
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label>
          To date
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <button type="submit" className={styles["secondary"] ?? ""}>
          Update range
        </button>
      </form>

      <LoadGate loading={result.loading} error={result.error} onRetry={result.reload}>
        {data ? (
          <>
            <section aria-labelledby="kpi-heading">
              <h2 id="kpi-heading" className={styles["flushTop"]}>
                Key metrics ({data.period.from} to {data.period.to})
              </h2>
              <dl className={styles["stats"]}>
                <Stat label="Recovery rate" value={data.recovery_rate_pct !== null ? `${data.recovery_rate_pct}%` : "-"} featured />
                <Stat label="Items recovered" value={data.recoveries} />
                <Stat label="Lost reports" value={data.lost_reports} />
                <Stat label="Found reports" value={data.found_reports} />
                <Stat label="Currently active reports" value={data.active_reports} />
                <Stat label="Claims submitted" value={data.claims.submitted} />
                <Stat label="Claims verified" value={data.claims.verified} />
                <Stat label="Claims rejected" value={data.claims.rejected} />
                <Stat label="Claims cancelled" value={data.claims.cancelled} />
                <Stat
                  label="Recovery rate (excluding withdrawn)"
                  value={data.recovery_rate_non_withdrawn_pct !== null ? `${data.recovery_rate_non_withdrawn_pct}%` : "-"}
                />
                <Stat label="Average recovery time" value={data.average_recovery_days !== null ? `${data.average_recovery_days} days` : "-"} />
                <Stat label="Median recovery time" value={data.median_recovery_days !== null ? `${data.median_recovery_days} days` : "-"} />
              </dl>
            </section>

            <div className={styles["twoCol"]}>
              <BreakdownTable
                title="Breakdown by category"
                headingId="by-category-heading"
                firstColumn="Category"
                caption="Report and recovery breakdown by category"
                rows={data.by_category.map((c) => ({ id: c.category_id, name: c.name, lost: c.lost, found: c.found, recoveries: c.recoveries }))}
              />
              <BreakdownTable
                title="Breakdown by location"
                headingId="by-location-heading"
                firstColumn="Location"
                caption="Report and recovery breakdown by location"
                rows={data.by_location.map((l) => ({ id: l.location_id, name: l.name, lost: l.lost, found: l.found, recoveries: l.recoveries }))}
              />
            </div>

            {data.monthly && data.monthly.length > 0 ? (
              <section aria-labelledby="monthly-heading">
                <h2 id="monthly-heading">Monthly volume trends</h2>
                <div className={styles["tableWrap"]}>
                  <table className={styles["table"]}>
                    <caption className="sr-only">Monthly report and recovery volume trends</caption>
                    <thead>
                      <tr>
                        <th scope="col">Month</th>
                        <th scope="col" className={styles["num"]}>Lost</th>
                        <th scope="col" className={styles["num"]}>Found</th>
                        <th scope="col" className={styles["num"]}>Recoveries</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.monthly.map((m) => (
                        <tr key={m.month}>
                          <td>{m.month}</td>
                          <td className={styles["num"]}>{m.lost}</td>
                          <td className={styles["num"]}>{m.found}</td>
                          <td className={styles["num"]}>{m.recoveries}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}
          </>
        ) : null}
      </LoadGate>
    </>
  );
}
