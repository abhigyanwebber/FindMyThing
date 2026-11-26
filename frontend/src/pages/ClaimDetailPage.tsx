import { useCallback, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { cancelClaim, deleteEvidence, evidenceUrl, getClaim, uploadEvidence, type Claim } from "../api/data";
import ActionForm from "../components/ActionForm";
import { toFormFailure } from "../components/formErrors";
import styles from "../components/Page.module.css";
import { Alert, fmtDate, LoadGate, Notice, StatusBadge } from "../components/ui";
import { useLoad } from "../useLoad";
import { usePageTitle } from "../usePageTitle";

const MAX_EVIDENCE = 3;
const MAX_BYTES = 5 * 1024 * 1024;
const TYPES = ["image/jpeg", "image/png", "image/webp"];

/** One of the student's own claims: status, moderator feedback, evidence management and cancellation. */
export default function ClaimDetailPage() {
  const { claimId = "" } = useParams();
  const location = useLocation();
  const flash = (location.state as { notice?: unknown } | null)?.notice;
  const load = useCallback((signal: AbortSignal) => getClaim(claimId, signal), [claimId]);
  const result = useLoad(load);
  const claim = result.data;
  usePageTitle(claim ? `Claim: ${claim.found_report.title}` : "Claim");

  return (
    <LoadGate loading={result.loading} error={result.error} onRetry={result.reload}>
      {claim ? (
        <article>
          {typeof flash === "string" ? <Notice>{flash}</Notice> : null}
          <h1>Claim for “{claim.found_report.title}”</h1>
          <dl className={styles["dl"]}>
            <dt>Status</dt>
            <dd>
              <StatusBadge status={claim.status} />
            </dd>
            <dt>Submitted</dt>
            <dd>{fmtDate(claim.created_at_utc)}</dd>
            <dt>Last change</dt>
            <dd>{fmtDate(claim.status_changed_at_utc)}</dd>
            <dt>Found report</dt>
            <dd>
              <Link to={`/reports/${claim.found_report_id}`}>{claim.found_report.title}</Link>
            </dd>
          </dl>
          <div className={styles["detailGrid"]}>
            <div className={styles["detailMain"]}>
              <h2>Your statement</h2>
              <p className={styles["statement"]}>{claim.claim_statement}</p>
              {claim.information_request.note ? (
                <section aria-labelledby="info-heading">
                  <h2 id="info-heading">Moderator asked for more information</h2>
                  <p className={styles["statement"]}>{claim.information_request.note}</p>
                  <p>Add evidence below to help the moderator.</p>
                </section>
              ) : null}
              {claim.decision.decision_note || claim.decision.reason_code ? (
                <section aria-labelledby="decision-heading">
                  <h2 id="decision-heading">Moderator decision</h2>
                  {claim.decision.reason_code ? <p>Reason: {claim.decision.reason_code.replace(/_/g, " ").toLowerCase()}</p> : null}
                  {claim.decision.decision_note ? <p className={styles["statement"]}>{claim.decision.decision_note}</p> : null}
                </section>
              ) : null}
            </div>
            <div className={styles["detailSide"]}>
              <EvidenceSection claim={claim} onChanged={result.reload} />
              {claim.status === "PENDING" || claim.status === "VERIFIED" ? (
                <section aria-labelledby="cancel-heading">
                  <h2 id="cancel-heading">Cancel this claim</h2>
                  <ActionForm
                    title="Cancel claim"
                    submitLabel="Cancel claim"
                    danger
                    onSubmit={async () => {
                      await cancelClaim(claim.claim_id, claim.version);
                      result.reload();
                    }}
                  />
                </section>
              ) : null}
            </div>
          </div>
        </article>
      ) : null}
    </LoadGate>
  );
}

function EvidenceSection({ claim, onChanged }: { claim: Claim; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const editable = claim.status === "PENDING" || claim.status === "VERIFIED";
  const remaining = MAX_EVIDENCE - claim.evidence.length;

  async function onFiles(list: FileList | null) {
    const files = list ? Array.from(list) : [];
    if (files.length === 0) return;
    setError(null);
    if (files.length > remaining) {
      setError(`You can add ${remaining} more photo${remaining === 1 ? "" : "s"} (maximum ${MAX_EVIDENCE}).`);
      return;
    }
    if (files.some((f) => !TYPES.includes(f.type))) {
      setError("Evidence must be JPEG, PNG or WebP images.");
      return;
    }
    if (files.some((f) => f.size > MAX_BYTES)) {
      setError("Each photo must be 5 MB or smaller.");
      return;
    }
    setBusy(true);
    try {
      await uploadEvidence(claim.claim_id, files);
      onChanged();
    } catch (e) {
      setError(toFormFailure(e, []).message);
    } finally {
      setBusy(false);
    }
  }

  async function onRemove(evidenceId: string) {
    setError(null);
    setBusy(true);
    try {
      await deleteEvidence(claim.claim_id, evidenceId);
      onChanged();
    } catch (e) {
      setError(toFormFailure(e, []).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="evidence-heading">
      <h2 id="evidence-heading">Evidence photos</h2>
      {error ? <Alert>{error}</Alert> : null}
      {claim.evidence.length === 0 ? <p>No evidence uploaded.</p> : null}
      <ul className={styles["thumbs"]}>
        {claim.evidence.map((ev, i) => (
          <li key={ev.evidence_id}>
            <img src={evidenceUrl(claim.claim_id, ev.evidence_id)} alt={`Evidence photo ${i + 1}`} />
            {editable ? (
              <button type="button" className={styles["danger"] ?? ""} disabled={busy} onClick={() => void onRemove(ev.evidence_id)}>
                Remove photo {i + 1}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {editable && remaining > 0 ? (
        <label className={styles["stack"]}>
          Add evidence (up to {remaining} more, JPEG, PNG or WebP, 5 MB each)
          <input type="file" multiple accept={TYPES.join(",")} disabled={busy} onChange={(e) => void onFiles(e.target.files)} />
        </label>
      ) : null}
    </section>
  );
}
