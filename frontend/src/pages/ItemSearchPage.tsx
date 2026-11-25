import { useCallback, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getReferenceData, listReports, type ReportStatus, type ReportType } from "../api/data";
import { LoadGate, Pager, StatusBadge } from "../components/ui";
import styles from "../components/Page.module.css";
import { useLoad } from "../useLoad";
import { usePageTitle } from "../usePageTitle";

const loadReference = (signal: AbortSignal) => getReferenceData(signal);
const PAGE_SIZE = 12;

/** Browse and filter campus reports (`GET /reports`). Filters live in the URL so results are linkable. */
export default function ItemSearchPage() {
  usePageTitle("Browse reports");
  const [params, setParams] = useSearchParams();
  const type = (params.get("type") ?? "") as ReportType | "";
  const status = (params.get("status") ?? "") as ReportStatus | "";
  const categoryId = params.get("category_id") ?? "";
  const locationId = params.get("location_id") ?? "";
  const q = params.get("q") ?? "";
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const [draftQ, setDraftQ] = useState(q);

  const reference = useLoad(loadReference);
  const load = useCallback(
    (signal: AbortSignal) =>
      listReports({ type, status, category_id: categoryId, location_id: locationId, q, page, page_size: PAGE_SIZE }, signal),
    [type, status, categoryId, locationId, q, page],
  );
  const results = useLoad(load);

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  }

  return (
    <>
      <h1>Browse reports</h1>
      <form
        className={styles["filters"]}
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setParam("q", draftQ.trim());
        }}
      >
        <label>
          Search
          <input type="search" value={draftQ} maxLength={100} onChange={(e) => setDraftQ(e.target.value)} />
        </label>
        <label>
          Type
          <select value={type} onChange={(e) => setParam("type", e.target.value)}>
            <option value="">All</option>
            <option value="LOST">Lost</option>
            <option value="FOUND">Found</option>
          </select>
        </label>
        <label>
          Category
          <select value={categoryId} onChange={(e) => setParam("category_id", e.target.value)}>
            <option value="">All</option>
            {reference.data?.categories.map((c) => (
              <option key={c.category_id} value={c.category_id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Location
          <select value={locationId} onChange={(e) => setParam("location_id", e.target.value)}>
            <option value="">All</option>
            {reference.data?.locations.map((l) => (
              <option key={l.location_id} value={l.location_id}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select value={status} onChange={(e) => setParam("status", e.target.value)}>
            <option value="">Active</option>
            <option value="RESOLVED">Resolved</option>
            <option value="WITHDRAWN">My withdrawn</option>
            <option value="CLOSED">My closed</option>
          </select>
        </label>
        <button type="submit" className={styles["secondary"]}>
          Search
        </button>
      </form>
      <LoadGate loading={results.loading} error={results.error} onRetry={results.reload}>
        {results.data && results.data.items.length === 0 ? <p>No reports match these filters.</p> : null}
        <ul className={styles["cards"]}>
          {results.data?.items.map((r) => (
            <li key={r.report_id} className={styles["card"]}>
              <h2>
                <Link to={`/reports/${r.report_id}`}>{r.title}</Link>
              </h2>
              <p className={styles["meta"]}>
                {r.report_type === "LOST" ? "Lost" : "Found"} · {r.category.name} · {r.location.name} · {r.occurred_on} ·{" "}
                <StatusBadge status={r.status} />
              </p>
            </li>
          ))}
        </ul>
        {results.data ? <Pager page={page} pageSize={PAGE_SIZE} total={results.data.total} onPage={(p) => setParam("page", String(p))} /> : null}
      </LoadGate>
    </>
  );
}
