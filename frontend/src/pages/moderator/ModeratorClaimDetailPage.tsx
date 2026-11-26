import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  claimAction,
  evidenceUrl,
  getModerationClaim,
  moderatorDeleteEvidence,
  recoverClaim,
  voidRecovery,
  type ModeratorClaim,
} from "../../api/data";
import ActionForm from "../../components/ActionForm";
import styles from "../../components/Page.module.css";
import { Alert, fmtDate, LoadGate, Notice, StatusBadge } from "../../components/ui";
import { useLoad } from "../../useLoad";
import { usePageTitle } from "../../usePageTitle";

const REJECT_REASONS = [
  { value: "INSUFFICIENT_EVIDENCE", label: "Insufficient evidence provided" },
  { value: "OWNERSHIP_NOT_CONFIRMED", label: "Ownership could not be confirmed" },
  { value: "DUPLICATE_CLAIM", label: "Duplicate claim" },
  { value: "OTHER", label: "Other (note required)" },
] as const;

const EVIDENCE_DELETE_REASONS = [
  { value: "INSUFFICIENT_EVIDENCE", label: "Irrelevant or invalid evidence" },
  { value: "OTHER", label: "Inappropriate / privacy violation (note required)" },
] as const;

/** Full moderator claim review (`GET /moderation/claims/:claimId`). */
export default function ModeratorClaimDetailPage() {
  const { claimId = "" } = useParams();
  const load = useCallback((signal: AbortSignal) => getModerationClaim(claimId, signal), [claimId]);
  const result = useLoad(load);
  const claim = result.data as ModeratorClaim | undefined;
  usePageTitle(claim ? `Review claim: ${claim.found_report.title}` : "Review claim");
  const [flash, setFlash] = useState<string | null>(null);

  return (
    <LoadGate loading={result.loading} error={result.error} onRetry={result.reload}>
      {claim ? (
        <article>
          {flash ? <Notice>{flash}</Notice> : null}
          <p>
            <Link to="/moderator">← Back to claims queue</Link>
          </p>
          <h1>Claim review for “{claim.found_report.title}”</h1>

          <dl className={styles["dl"]}>
            <dt>Status</dt>
            <dd>
              <StatusBadge status={claim.status} />
            </dd>
            <dt>Claimant</dt>
            <dd>
              {claim.claimant.display_name} ({claim.claimant.email})
            </dd>
            <dt>Submitted</dt>
            <dd>{fmtDate(claim.created_at_utc)}</dd>
            <dt>Last updated</dt>
            <dd>{fmtDate(claim.status_changed_at_utc)}</dd>
            {claim.reviewer ? (
              <>
                <dt>Last reviewed by</dt>
                <dd>{claim.reviewer.display_name}</dd>
              </>
            ) : null}
            <dt>Found item report</dt>
            <dd>
              <Link to={`/reports/${claim.found_report_id}`}>
                {claim.related_reports.found.title} ({claim.related_reports.found.status})
              </Link>
            </dd>
            {claim.lost_report_id && claim.related_reports.lost ? (
              <>
                <dt>Linked lost item report</dt>
                <dd>
                  <Link to={`/reports/${claim.lost_report_id}`}>
                    {claim.related_reports.lost.title} ({claim.related_reports.lost.status})
                  </Link>
                </dd>
              </>
            ) : null}
          </dl>

          <div className={styles["detailGrid"]}>
            <div className={styles["detailMain"]}>
              <section aria-labelledby="statement-heading">
                <h2 id="statement-heading">Claim statement</h2>
                <p className={styles["statement"]}>{claim.claim_statement}</p>
              </section>

              {claim.information_request.note ? (
                <section aria-labelledby="info-req-heading">
                  <h2 id="info-req-heading">Active information request</h2>
                  <p className={styles["statement"]}>{claim.information_request.note}</p>
                  <p className={styles["meta"]}>
                    Requested at {fmtDate(claim.information_request.requested_at_utc ?? "")}
                  </p>
                </section>
              ) : null}

              {claim.decision.decision_note || claim.decision.reason_code ? (
                <section aria-labelledby="decision-heading">
                  <h2 id="decision-heading">Decision record</h2>
                  {claim.decision.reason_code ? (
                    <p>
                      Reason: <strong>{claim.decision.reason_code.replace(/_/g, " ")}</strong>
                    </p>
                  ) : null}
                  {claim.decision.decision_note ? (
                    <p className={styles["statement"]}>{claim.decision.decision_note}</p>
                  ) : null}
                  {claim.decision.reviewed_at_utc ? (
                    <p className={styles["meta"]}>Reviewed at {fmtDate(claim.decision.reviewed_at_utc)}</p>
                  ) : null}
                </section>
              ) : null}

              {claim.recovery ? (
                <section aria-labelledby="recovery-heading">
                  <h2 id="recovery-heading">Recovery record</h2>
                  <dl className={styles["dl"]}>
                    <dt>Recovery status</dt>
                    <dd>{claim.recovery.status}</dd>
                    {claim.recovery.completed_at_utc ? (
                      <>
                        <dt>Completed</dt>
                        <dd>{fmtDate(claim.recovery.completed_at_utc)}</dd>
                      </>
                    ) : null}
                    {claim.recovery.voided_at_utc ? (
                      <>
                        <dt>Voided</dt>
                        <dd>
                          {fmtDate(claim.recovery.voided_at_utc)} ({claim.recovery.void_reason_code})
                        </dd>
                      </>
                    ) : null}
                  </dl>
                </section>
              ) : null}

              <ModeratorEvidenceSection claim={claim} onChanged={result.reload} />
            </div>
            <div className={styles["detailSide"]}>
              <section aria-labelledby="mod-actions-heading">
                <h2 id="mod-actions-heading">Moderation actions</h2>
                <div className={styles["actions"]}>
                  {claim.status === "PENDING" ? (
                    <>
                      <ActionForm
                        title="Verify claim"
                        submitLabel="Confirm verification"
                        noteLabel="Verification note (optional)"
                        onSubmit={async ({ note }) => {
                          await claimAction(claim.claim_id, "verify", {
                            expected_version: claim.version,
                            decision_note: note || undefined,
                          });
                          setFlash("Claim verified. Ready for recovery handover.");
                          result.reload();
                        }}
                      />

                      <ActionForm
                        title="Request additional information"
                        submitLabel="Send information request"
                        noteLabel="Information requested (required, 10-1000 chars)"
                        noteRequired
                        noteMin={10}
                        noteMax={1000}
                        onSubmit={async ({ note }) => {
                          await claimAction(claim.claim_id, "request-information", {
                            expected_version: claim.version,
                            decision_note: note,
                          });
                          setFlash("Information requested from student.");
                          result.reload();
                        }}
                      />

                      <ActionForm
                        title="Reject claim"
                        submitLabel="Reject claim"
                        danger
                        reasons={REJECT_REASONS}
                        noteLabel="Rejection note (required if reason is Other)"
                        onSubmit={async ({ reason, note }) => {
                          await claimAction(claim.claim_id, "reject", {
                            expected_version: claim.version,
                            reason_code: reason,
                            decision_note: note || undefined,
                          });
                          setFlash("Claim rejected.");
                          result.reload();
                        }}
                      />
                    </>
                  ) : null}

                  {claim.status === "VERIFIED" ? (
                    <>
                      <ActionForm
                        title="Complete in-person recovery handover"
                        submitLabel="Confirm item handover to claimant"
                        noteLabel="Handover note (optional)"
                        onSubmit={async ({ note }) => {
                          await recoverClaim(claim.claim_id, claim.version, note || undefined);
                          setFlash("Recovery completed! Associated reports marked resolved.");
                          result.reload();
                        }}
                      />

                      <ActionForm
                        title="Revoke verification"
                        submitLabel="Revoke verification"
                        danger
                        noteLabel="Revocation note (optional)"
                        onSubmit={async ({ note }) => {
                          await claimAction(claim.claim_id, "revoke-verification", {
                            expected_version: claim.version,
                            decision_note: note || undefined,
                          });
                          setFlash("Verification revoked. Claim returned to pending.");
                          result.reload();
                        }}
                      />
                    </>
                  ) : null}

                  {claim.status === "RECOVERED" && claim.recovery && claim.recovery.status === "COMPLETED" ? (
                    <ActionForm
                      title="Void recovery handover"
                      submitLabel="Void recovery"
                      danger
                      noteLabel="Reason for voiding recovery (required, 1-1000 chars)"
                      noteRequired
                      noteMin={1}
                      noteMax={1000}
                      onSubmit={async ({ note }) => {
                        if (!claim.recovery) return;
                        await voidRecovery(claim.recovery.recovery_id, claim.version, note);
                        setFlash("Recovery voided. Claim returned to verified status.");
                        result.reload();
                      }}
                    />
                  ) : null}
                </div>
              </section>
            </div>
          </div>

          {claim.history && claim.history.length > 0 ? (
            <section aria-labelledby="history-heading">
              <h2 id="history-heading">Audit timeline</h2>
              <div className={styles["tableWrap"]}>
                <table className={styles["table"]}>
                  <caption className="sr-only">Claim status transition history</caption>
                  <thead>
                    <tr>
                      <th scope="col">Time</th>
                      <th scope="col">Transition</th>
                      <th scope="col">Actor</th>
                      <th scope="col">Reason</th>
                      <th scope="col">Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {claim.history.map((h, idx) => (
                      <tr key={idx}>
                        <td>{fmtDate(h.changed_at_utc)}</td>
                        <td>
                          {h.old_status ? <StatusBadge status={h.old_status} /> : "—"} →{" "}
                          <StatusBadge status={h.new_status} />
                        </td>
                        <td>{h.actor_display_name ?? "System"}</td>
                        <td>{h.reason_code ?? "—"}</td>
                        <td>{h.note ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}
        </article>
      ) : null}
    </LoadGate>
  );
}

function ModeratorEvidenceSection({
  claim,
  onChanged,
}: {
  claim: ModeratorClaim;
  onChanged: () => void;
}) {
  const [error, setError] = useState<string | null>(null);

  return (
    <section aria-labelledby="mod-evidence-heading">
      <h2 id="mod-evidence-heading">Claim evidence</h2>
      {error ? <Alert>{error}</Alert> : null}
      {claim.evidence.length === 0 ? <p>No evidence submitted by claimant.</p> : null}
      <ul className={styles["thumbs"]}>
        {claim.evidence.map((ev, i) => (
          <li key={ev.evidence_id}>
            <img
              src={evidenceUrl(claim.claim_id, ev.evidence_id)}
              alt={`Claim evidence photo ${i + 1}`}
            />
            <p className={styles["meta"]}>
              Uploaded {fmtDate(ev.uploaded_at_utc)} ({(ev.size_bytes / 1024).toFixed(0)} KB)
            </p>
            {claim.status === "PENDING" || claim.status === "VERIFIED" ? (
              <ActionForm
                title={`Remove photo ${i + 1}`}
                submitLabel="Remove photo"
                danger
                reasons={EVIDENCE_DELETE_REASONS}
                noteLabel="Reason note (required if Other)"
                onSubmit={async ({ reason, note }) => {
                  setError(null);
                  try {
                    await moderatorDeleteEvidence(claim.claim_id, ev.evidence_id, reason, note || undefined);
                    onChanged();
                  } catch (e) {
                    setError(e instanceof Error ? e.message : "Failed to remove evidence");
                  }
                }}
              />
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
