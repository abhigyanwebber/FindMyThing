import { useCallback, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  closeReport,
  deleteReportPhoto,
  getReferenceData,
  getReport,
  listReports,
  moderatorCorrectReport,
  reopenReport,
  reportPhotoUrl,
  submitClaim,
  updateReport,
  uploadReportPhoto,
  withdrawReport,
  type Page,
  type Report,
} from "../api/data";
import ActionForm from "../components/ActionForm";
import { toFormFailure } from "../components/formErrors";
import MatchesPanel from "../components/MatchesPanel";
import styles from "../components/Page.module.css";
import formStyles from "../components/Form.module.css";
import { Alert, fmtDate, LoadGate, Notice, StatusBadge } from "../components/ui";
import { useAuth } from "../context/auth-context";
import { useLoad } from "../useLoad";
import { usePageTitle } from "../usePageTitle";

const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
const CLOSE_REASONS = [
  { value: "INVALID_REPORT", label: "Invalid report" },
  { value: "DUPLICATE_REPORT", label: "Duplicate report" },
  { value: "INAPPROPRIATE_CONTENT", label: "Inappropriate content" },
  { value: "ADMINISTRATIVE_CLOSURE", label: "Administrative closure" },
  { value: "OTHER", label: "Other" },
] as const;

/** One report: safe fields, photo, role-specific actions (contract 4.2, 4.3, 4.4). Roles only choose what is shown; the API enforces access. */
export default function ReportDetailPage() {
  const { reportId = "" } = useParams();
  const { state } = useAuth();
  const location = useLocation();
  const flash = (location.state as { notice?: unknown } | null)?.notice;
  const load = useCallback((signal: AbortSignal) => getReport(reportId, signal), [reportId]);
  const result = useLoad(load);
  const report = result.data;
  usePageTitle(report ? report.title : "Report");
  const role = state.status === "authenticated" ? state.user.role : null;
  const hasSide = Boolean(report?.is_owner) || Boolean(report?.can_claim && role === "STUDENT") || role === "MODERATOR";

  return (
    <LoadGate loading={result.loading} error={result.error} onRetry={result.reload}>
      {report ? (
        <article>
          {typeof flash === "string" ? <Notice>{flash}</Notice> : null}
          <h1>{report.title}</h1>
          <dl className={styles["dl"]}>
            <dt>Type</dt>
            <dd>{report.report_type === "LOST" ? "Lost item" : "Found item"}</dd>
            <dt>Status</dt>
            <dd>
              <StatusBadge status={report.status} />
            </dd>
            <dt>Category</dt>
            <dd>{report.category.name}</dd>
            <dt>Location</dt>
            <dd>
              {report.location.zone_name} – {report.location.name}
            </dd>
            <dt>Date</dt>
            <dd>{report.occurred_on}</dd>
            <dt>Reported by</dt>
            <dd>{report.reporter.display_name}</dd>
            <dt>Last updated</dt>
            <dd>{fmtDate(report.updated_at_utc)}</dd>
          </dl>
          <div className={hasSide ? styles["detailGrid"] : undefined}>
            <div className={styles["detailMain"]}>
              <p className={styles["prose"]}>{report.description}</p>
              <PhotoSection report={report} role={role} onChanged={result.reload} />
            </div>
            {hasSide ? (
              <div className={styles["detailSide"]}>
                {report.is_owner ? <OwnerActions report={report} onChanged={result.reload} /> : null}
                {report.can_claim && role === "STUDENT" ? <ClaimForm report={report} /> : null}
                {role === "MODERATOR" ? <ModeratorReportActions report={report} onChanged={result.reload} /> : null}
              </div>
            ) : null}
          </div>
          {(report.is_owner && report.status === "ACTIVE") || role === "MODERATOR" ? (
            <MatchesPanel reportId={report.report_id} moderator={role === "MODERATOR"} canRecalculate={report.status === "ACTIVE"} />
          ) : null}
        </article>
      ) : null}
    </LoadGate>
  );
}

function PhotoSection({ report, role, onChanged }: { report: Report; role: string | null; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canManage = (report.is_owner || role === "MODERATOR") && (report.status === "ACTIVE" || report.status === "RESOLVED");
  const canUpload = report.is_owner === true && !report.has_photo && canManage;

  async function onFile(file: File | null) {
    if (!file) return;
    setError(null);
    if (file.size > MAX_PHOTO_BYTES) {
      setError("The photo must be 5 MB or smaller.");
      return;
    }
    setBusy(true);
    try {
      await uploadReportPhoto(report.report_id, file);
      onChanged();
    } catch (e) {
      setError(toFormFailure(e, []).message);
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    setError(null);
    setBusy(true);
    try {
      await deleteReportPhoto(report.report_id);
      onChanged();
    } catch (e) {
      setError(toFormFailure(e, []).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="photo-heading">
      <h2 id="photo-heading">Photo</h2>
      {error ? <Alert>{error}</Alert> : null}
      {report.has_photo ? (
        <>
          <img className={styles["photo"]} src={reportPhotoUrl(report.report_id)} alt={`Photo of ${report.title}`} />
          {canManage ? (
            <p>
              <button type="button" className={styles["danger"]} disabled={busy} onClick={onDelete}>
                Remove photo
              </button>
            </p>
          ) : null}
        </>
      ) : (
        <p>No photo.</p>
      )}
      {canUpload ? (
        <label className={styles["stack"]}>
          Add a photo (JPEG, PNG or WebP, up to 5 MB)
          <input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={(e) => void onFile(e.target.files?.[0] ?? null)} />
        </label>
      ) : null}
    </section>
  );
}

function OwnerActions({ report, onChanged }: { report: Report; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(report.title);
  const [description, setDescription] = useState(report.description);
  const [occurredOn, setOccurredOn] = useState(report.occurred_on);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (report.status !== "ACTIVE") return null;

  async function onSaveEdit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await updateReport(report.report_id, {
        title: title.trim(),
        description: description.trim(),
        occurred_on: occurredOn,
        expected_version: report.version,
      });
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(toFormFailure(err, []).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="owner-heading">
      <h2 id="owner-heading">Manage your report</h2>
      {error ? <Alert>{error}</Alert> : null}
      {!editing ? (
        <div className={styles["actions"]}>
          <button type="button" className={styles["secondary"] ?? ""} onClick={() => setEditing(true)}>
            Edit report details
          </button>
        </div>
      ) : (
        <form className={formStyles["formSpaced"]} onSubmit={onSaveEdit}>
          <h3>Edit report details</h3>
          <label className={styles["stack"]}>
            Title
            <input required maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className={styles["stack"]}>
            Description
            <textarea required rows={4} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <label className={styles["stack"]}>
            Occurred on
            <input type="date" required value={occurredOn} onChange={(e) => setOccurredOn(e.target.value)} />
          </label>
          <div className={styles["actions"]}>
            <button type="submit" className={formStyles["primary"]} disabled={busy}>
              {busy ? "Saving…" : "Save changes"}
            </button>
            <button type="button" className={styles["secondary"] ?? ""} disabled={busy} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      <ActionForm
        title="Withdraw this report"
        submitLabel="Withdraw report"
        danger
        noteLabel="Note"
        onSubmit={async () => {
          await withdrawReport(report.report_id, report.version);
          onChanged();
        }}
      />
    </section>
  );
}

function ClaimForm({ report }: { report: Report }) {
  const navigate = useNavigate();
  const [statement, setStatement] = useState("");
  const [lostReportId, setLostReportId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; fields: readonly string[] } | null>(null);
  const myReports = useLoad<Page<Report>>((signal) => listReports({ type: "LOST", status: "ACTIVE", page_size: 50 }, signal));

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const claim = await submitClaim(report.report_id, statement.trim(), lostReportId || undefined);
      navigate(`/my/claims/${claim.claim_id}`, { state: { notice: "Claim submitted. You can add up to three evidence photos below." } });
    } catch (e) {
      const failure = toFormFailure(e, ["claim_statement", "lost_report_id"]);
      setError({ message: failure.message, fields: failure.fields["claim_statement"] ?? [] });
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="claim-heading">
      <h2 id="claim-heading">Is this yours?</h2>
      <p>
        Describe details only the owner would know. Moderators review your claim; the finder never sees it. Do not include contact details.
      </p>
      <form className={formStyles["form"]} onSubmit={onSubmit}>
        {error ? (
          <p role="alert" className={formStyles["banner"]}>
            {error.message}
          </p>
        ) : null}
        <div className={styles["stack"]}>
          {myReports.data && myReports.data.items.length > 0 ? (
            <label>
              Link to your lost item report (optional)
              <select value={lostReportId} onChange={(e) => setLostReportId(e.target.value)}>
                <option value="">None (standalone claim)</option>
                {myReports.data.items.map((r) => (
                  <option key={r.report_id} value={r.report_id}>
                    {r.title} ({r.occurred_on})
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label>
            Claim statement
            <textarea required rows={5} minLength={10} maxLength={2000} value={statement} onChange={(e) => setStatement(e.target.value)} aria-invalid={error ? error.fields.length > 0 : false} />
          </label>
          <span className={formStyles["hint"]}>10 to 2,000 characters.</span>
          {error && error.fields.length > 0 ? <span className={formStyles["error"]}>{error.fields.join(" ")}</span> : null}
        </div>
        <button type="submit" className={formStyles["primary"]} disabled={busy}>
          {busy ? "Submitting…" : "Submit claim"}
        </button>
      </form>
      <p>
        <Link to="/my/claims">View my claims</Link>
      </p>
    </section>
  );
}

function ModeratorReportActions({ report, onChanged }: { report: Report; onChanged: () => void }) {
  const [correcting, setCorrecting] = useState(false);
  const [title, setTitle] = useState(report.title);
  const [description, setDescription] = useState(report.description);
  const [occurredOn, setOccurredOn] = useState(report.occurred_on);
  const [categoryId, setCategoryId] = useState(report.category.category_id);
  const [locationId, setLocationId] = useState(report.location.location_id);
  const [decisionNote, setDecisionNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reference = useLoad((signal) => getReferenceData(signal));

  async function onSaveCorrect(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await moderatorCorrectReport(report.report_id, {
        title: title.trim(),
        description: description.trim(),
        occurred_on: occurredOn,
        category_id: categoryId,
        location_id: locationId,
        decision_note: decisionNote.trim() ? decisionNote.trim() : undefined,
        expected_version: report.version,
      });
      setCorrecting(false);
      onChanged();
    } catch (err) {
      setError(toFormFailure(err, []).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="mod-report-heading">
      <h2 id="mod-report-heading">Moderation</h2>
      {error ? <Alert>{error}</Alert> : null}
      {!correcting ? (
        <div className={styles["actions"]}>
          <button type="button" className={styles["secondary"] ?? ""} onClick={() => setCorrecting(true)}>
            Correct report fields
          </button>
        </div>
      ) : (
        <form className={formStyles["formSpaced"]} onSubmit={onSaveCorrect}>
          <h3>Correct report fields</h3>
          <label className={styles["stack"]}>
            Title
            <input required maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className={styles["stack"]}>
            Category
            <select required value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
              {reference.data?.categories.map((c) => (
                <option key={c.category_id} value={c.category_id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className={styles["stack"]}>
            Location
            <select required value={locationId} onChange={(e) => setLocationId(e.target.value)}>
              {reference.data?.locations
                .filter((l) => !l.is_zone)
                .map((l) => (
                  <option key={l.location_id} value={l.location_id}>
                    {l.zone_name} – {l.name}
                  </option>
                ))}
            </select>
          </label>
          <label className={styles["stack"]}>
            Description
            <textarea required rows={4} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <label className={styles["stack"]}>
            Occurred on
            <input type="date" required value={occurredOn} onChange={(e) => setOccurredOn(e.target.value)} />
          </label>
          <label className={styles["stack"]}>
            Decision note (optional)
            <input maxLength={1000} value={decisionNote} onChange={(e) => setDecisionNote(e.target.value)} placeholder="Audit reason for correction" />
          </label>
          <div className={styles["actions"]}>
            <button type="submit" className={formStyles["primary"]} disabled={busy}>
              {busy ? "Saving correction…" : "Save correction"}
            </button>
            <button type="button" className={styles["secondary"] ?? ""} disabled={busy} onClick={() => setCorrecting(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {report.status === "ACTIVE" ? (
        <ActionForm
          title="Close this report"
          submitLabel="Close report"
          danger
          reasons={CLOSE_REASONS}
          onSubmit={async ({ reason, note }) => {
            await closeReport(report.report_id, reason, report.version, note || undefined);
            onChanged();
          }}
        />
      ) : null}
      {report.status === "WITHDRAWN" || report.status === "CLOSED" ? (
        <ActionForm
          title="Reopen this report"
          submitLabel="Reopen report"
          onSubmit={async ({ note }) => {
            await reopenReport(report.report_id, report.version, note || undefined);
            onChanged();
          }}
        />
      ) : null}
    </section>
  );
}
