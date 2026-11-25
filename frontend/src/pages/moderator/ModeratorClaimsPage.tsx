import { useCallback } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { listModerationClaims, type ClaimStatus } from "../../api/data";
import styles from "../../components/Page.module.css";
import { fmtDate, LoadGate, Pager, StatusBadge } from "../../components/ui";
import { useLoad } from "../../useLoad";
import { usePageTitle } from "../../usePageTitle";

const PAGE_SIZE = 20;
const STATUS_TABS: { status: ClaimStatus | ""; label: string }[] = [
  { status: "", label: "All" },
  { status: "PENDING", label: "Pending review" },
  { status: "VERIFIED", label: "Verified (ready for handover)" },
  { status: "RECOVERED", label: "Recovered" },
  { status: "REJECTED", label: "Rejected" },
  { status: "CANCELLED", label: "Cancelled" },
];

/** Moderator claims dashboard (`GET /moderation/claims`). Filterable by claim status. */
export default function ModeratorClaimsPage() {
  usePageTitle("Moderation: Claims");
  const [params, setParams] = useSearchParams();
  const status = (params.get("status") ?? "") as ClaimStatus | "";
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);

  const load = useCallback(
    (signal: AbortSignal) => listModerationClaims(status, page, signal),
    [status, page],
  );
  const results = useLoad(load);

  function setStatus(nextStatus: ClaimStatus | "") {
    const next = new URLSearchParams(params);
    if (nextStatus) next.set("status", nextStatus);
    else next.delete("status");
    next.delete("page");
    setParams(next);
  }

  function setPage(nextPage: number) {
    const next = new URLSearchParams(params);
    if (nextPage > 1) next.set("page", String(nextPage));
    else next.delete("page");
    setParams(next);
  }

  return (
    <>
      <h1>Claims review queue</h1>
      <p>Supervise student claims, verify proof of ownership, and oversee in-person recovery handovers.</p>

      <div className={styles["tabs"]} role="group" aria-label="Filter claims by status">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.status || "ALL"}
            type="button"
            className={styles["secondary"] ?? ""}
            aria-pressed={status === tab.status}
            onClick={() => setStatus(tab.status)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <LoadGate loading={results.loading} error={results.error} onRetry={results.reload}>
        {results.data && results.data.items.length === 0 ? (
          <p>No claims found in this queue.</p>
        ) : null}

        <div className={styles["tableWrap"]}>
          <table className={styles["table"]}>
            <caption className="sr-only">Claims in moderation queue</caption>
            <thead>
              <tr>
                <th scope="col">Found item</th>
                <th scope="col">Claimant</th>
                <th scope="col">Status</th>
                <th scope="col">Evidence</th>
                <th scope="col">Submitted</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {results.data?.items.map((c) => (
                <tr key={c.claim_id}>
                  <td>
                    <strong>{c.found_report.title}</strong>
                    {c.has_linked_lost_report ? (
                      <div className={styles["meta"]}>Linked to lost report</div>
                    ) : null}
                  </td>
                  <td>{c.claimant?.display_name ?? "Student"}</td>
                  <td>
                    <StatusBadge status={c.status} />
                  </td>
                  <td>
                    {typeof c.evidence_count === "number"
                      ? `${c.evidence_count} photo${c.evidence_count === 1 ? "" : "s"}`
                      : "—"}
                  </td>
                  <td>{fmtDate(c.created_at_utc)}</td>
                  <td>
                    <Link to={`/moderator/claims/${c.claim_id}`}>Review claim</Link>
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
