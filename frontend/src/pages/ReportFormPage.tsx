import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createReport, getReferenceData, uploadReportPhoto, type ReportType } from "../api/data";
import Field from "../components/Field";
import formStyles from "../components/Form.module.css";
import { toFormFailure, type FormFailure } from "../components/formErrors";
import { LoadGate } from "../components/ui";
import styles from "../components/Page.module.css";
import { useAuth } from "../context/auth-context";
import { useLoad } from "../useLoad";
import { usePageTitle } from "../usePageTitle";

const loadReference = (signal: AbortSignal) => getReferenceData(signal);
const FIELDS = ["report_type", "category_id", "location_id", "title", "description", "occurred_on"] as const;
const MAX_PHOTO_BYTES = 5 * 1024 * 1024;

function isoDate(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Two-step flow (contract 4.2): create the report, then upload the optional photo. A failed upload never undoes the report. */
export default function ReportFormPage() {
  usePageTitle("New report");
  const { state } = useAuth();
  const navigate = useNavigate();
  const reference = useLoad(loadReference);
  const [type, setType] = useState<ReportType>("LOST");
  const [categoryId, setCategoryId] = useState("");
  const [locationId, setLocationId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [occurredOn, setOccurredOn] = useState(isoDate());
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<FormFailure | null>(null);

  if (state.status === "authenticated" && state.user.role !== "STUDENT") {
    return <p>Only students can create reports.</p>;
  }

  function onPhoto(file: File | null) {
    setPhotoError(null);
    if (file && file.size > MAX_PHOTO_BYTES) {
      setPhotoError("The photo must be 5 MB or smaller.");
      setPhoto(null);
      return;
    }
    setPhoto(file);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure(null);
    let reportId: string;
    try {
      const report = await createReport({
        report_type: type,
        category_id: categoryId,
        location_id: locationId,
        title,
        description,
        occurred_on: occurredOn,
      });
      reportId = report.report_id;
    } catch (error) {
      setFailure(toFormFailure(error, FIELDS));
      setBusy(false);
      return;
    }
    let notice: string | null = null;
    if (photo) {
      try {
        await uploadReportPhoto(reportId, photo);
      } catch {
        notice = "Your report was created, but the photo could not be uploaded. You can try again from the report page.";
      }
    }
    navigate(`/reports/${reportId}`, { replace: true, state: notice ? { notice } : null });
  }

  return (
    <>
      <h1>Report an item</h1>
      <LoadGate loading={reference.loading} error={reference.error} onRetry={reference.reload}>
        <form className={formStyles["form"]} onSubmit={onSubmit}>
          {failure ? (
            <p role="alert" className={formStyles["banner"]}>
              {failure.message}
            </p>
          ) : null}
          <fieldset className={styles["stack"]}>
            <legend>I…</legend>
            <label>
              <span>
                <input type="radio" name="type" checked={type === "LOST"} onChange={() => setType("LOST")} /> lost an item
              </span>
            </label>
            <label>
              <span>
                <input type="radio" name="type" checked={type === "FOUND"} onChange={() => setType("FOUND")} /> found an item
              </span>
            </label>
          </fieldset>
          <div className={styles["stack"]}>
            <label>
              Category
              <select required value={categoryId} onChange={(e) => setCategoryId(e.target.value)} aria-invalid={Boolean(failure?.fields["category_id"])}>
                <option value="">Choose…</option>
                {reference.data?.categories.map((c) => (
                  <option key={c.category_id} value={c.category_id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            {failure?.fields["category_id"] ? <span className={formStyles["error"]}>{failure.fields["category_id"].join(" ")}</span> : null}
            <label>
              Location
              <select required value={locationId} onChange={(e) => setLocationId(e.target.value)} aria-invalid={Boolean(failure?.fields["location_id"])}>
                <option value="">Choose…</option>
                {reference.data?.locations
                  .filter((l) => !l.is_zone)
                  .map((l) => (
                    <option key={l.location_id} value={l.location_id}>
                      {l.zone_name} – {l.name}
                    </option>
                  ))}
              </select>
            </label>
            {failure?.fields["location_id"] ? <span className={formStyles["error"]}>{failure.fields["location_id"].join(" ")}</span> : null}
          </div>
          <Field id="title" label="Title" type="text" value={title} onChange={setTitle} autoComplete="off" maxLength={120} hint="5 to 120 characters." errors={failure?.fields["title"]} />
          <div className={styles["stack"]}>
            <label>
              Description
              <textarea required rows={5} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} aria-invalid={Boolean(failure?.fields["description"])} />
            </label>
            <span className={formStyles["hint"]}>10 to 2,000 characters. Do not include private contact details.</span>
            {failure?.fields["description"] ? <span className={formStyles["error"]}>{failure.fields["description"].join(" ")}</span> : null}
            <label>
              Date {type === "LOST" ? "lost" : "found"}
              <input type="date" required value={occurredOn} min={isoDate(-3650)} max={isoDate(1)} onChange={(e) => setOccurredOn(e.target.value)} />
            </label>
            {failure?.fields["occurred_on"] ? <span className={formStyles["error"]}>{failure.fields["occurred_on"].join(" ")}</span> : null}
            <label>
              Photo (optional, image up to 5 MB)
              <input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => onPhoto(e.target.files?.[0] ?? null)} />
            </label>
            {photoError ? <span className={formStyles["error"]}>{photoError}</span> : null}
          </div>
          <button type="submit" className={formStyles["primary"]} disabled={busy}>
            {busy ? "Submitting…" : "Submit report"}
          </button>
        </form>
      </LoadGate>
    </>
  );
}
