/**
 * Typed resource endpoints (contract 4.2-4.5). Shapes mirror docs/IMPLEMENTATION_CONTRACTS.md; the backend is
 * authoritative, so responses are only structurally typed here (no extra runtime validation beyond the envelope).
 */
import { getApiBaseUrl } from "../config";
import { apiRequest, apiRequestNoContent } from "./client";

export type ReportType = "LOST" | "FOUND";
export type ReportStatus = "ACTIVE" | "RESOLVED" | "WITHDRAWN" | "CLOSED";
export type ClaimStatus = "PENDING" | "VERIFIED" | "RECOVERED" | "REJECTED" | "CANCELLED";

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface Report {
  report_id: string;
  report_type: ReportType;
  category: { category_id: string; name: string };
  location: { location_id: string; name: string; zone_name: string };
  title: string;
  description: string;
  occurred_on: string;
  status: ReportStatus;
  reporter: { display_name: string };
  created_at_utc: string;
  updated_at_utc: string;
  status_changed_at_utc: string;
  version: number;
  has_photo: boolean;
  is_owner?: boolean;
  can_claim?: boolean;
  claim_activity?: { has_active_claim: boolean };
  status_reason_code?: string | null;
}

export interface ReferenceData {
  campus: { display_name: string; timezone: string };
  categories: { category_id: string; name: string }[];
  locations: { location_id: string; name: string; is_zone: boolean; zone_name: string }[];
}

export interface EvidenceMeta {
  evidence_id: string;
  content_type: string;
  size_bytes: number;
  uploaded_at_utc: string;
}

export interface ReportRef {
  report_id: string;
  title: string;
  status: string;
}

export interface Claim {
  claim_id: string;
  found_report_id: string;
  lost_report_id: string | null;
  claim_statement: string;
  status: ClaimStatus;
  version: number;
  created_at_utc: string;
  updated_at_utc: string;
  status_changed_at_utc: string;
  decision: { reason_code: string | null; decision_note: string | null; reviewed_at_utc: string | null };
  information_request: { note: string | null; requested_at_utc: string | null };
  evidence: EvidenceMeta[];
  found_report: ReportRef;
  lost_report: ReportRef | null;
}

export interface RelatedReport {
  report_id: string;
  report_type: ReportType;
  title: string;
  description: string;
  category_name: string;
  location_name: string;
  occurred_on: string;
  status: ReportStatus;
  version: number;
  reporter: { display_name: string };
}

export interface ModeratorClaim extends Claim {
  claimant: { user_id: string; display_name: string; email: string };
  reviewer: { user_id: string; display_name: string } | null;
  history: {
    old_status: string | null;
    new_status: string;
    actor_display_name: string | null;
    reason_code: string | null;
    note: string | null;
    changed_at_utc: string;
  }[];
  related_reports: { found: RelatedReport; lost: RelatedReport | null };
  recovery?: Recovery | null;
}

export interface Recovery {
  recovery_id: string;
  claim_id: string;
  found_report_id: string;
  lost_report_id: string | null;
  status: string;
  completed_at_utc: string | null;
  voided_at_utc: string | null;
  void_reason_code: string | null;
}

export interface MatchItem {
  match_id: string;
  counterpart_report: {
    report_id: string;
    report_type: ReportType;
    title: string;
    category_name: string;
    location_name: string;
    occurred_on: string;
    status: string;
  };
  score: number;
  factors: Record<string, unknown>;
  explanation: unknown;
  calculated_at_utc: string;
  algorithm_version: string;
  match_status: string;
}

export interface Analytics {
  period: { from: string; to: string; as_of_utc: string };
  lost_reports: number;
  found_reports: number;
  active_reports: number;
  claims: { submitted: number; verified: number; rejected: number; cancelled: number };
  recoveries: number;
  recovery_rate_pct: number | null;
  recovery_rate_non_withdrawn_pct: number | null;
  by_category: { category_id: string; name: string; lost: number; found: number; recoveries: number }[];
  by_location: { location_id: string; name: string; lost: number; found: number; recoveries: number }[];
  monthly: { month: string; lost: number; found: number; recoveries: number }[];
  average_recovery_days: number | null;
  median_recovery_days: number | null;
}

export interface ActivityItem {
  activity_id: string;
  event_type: string;
  target_type: string;
  target_id: string | null;
  actor: { user_id: string; display_name: string } | null;
  created_at_utc: string;
  outcome: string;
  correlation_id: string;
  metadata: Record<string, unknown>;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

const post = <T>(path: string, json: unknown) => apiRequest<T>(path, { method: "POST", json });

// ---- reference data and reports
export const getReferenceData = (signal?: AbortSignal) =>
  apiRequest<ReferenceData>("/reference-data", signal ? { signal } : {});

export interface ReportFilters {
  type?: ReportType | "";
  status?: ReportStatus | "";
  category_id?: string;
  location_id?: string;
  q?: string;
  page?: number;
  page_size?: number;
}
export const listReports = (f: ReportFilters, signal?: AbortSignal) =>
  apiRequest<Page<Report>>(`/reports${qs({ ...f })}`, signal ? { signal } : {});

export interface NewReport {
  report_type: ReportType;
  category_id: string;
  location_id: string;
  title: string;
  description: string;
  occurred_on: string;
}
export const createReport = async (body: NewReport) => (await post<{ report: Report }>("/reports", body)).report;
export const getReport = async (id: string, signal?: AbortSignal) =>
  (await apiRequest<{ report: Report }>(`/reports/${id}`, signal ? { signal } : {})).report;
export const updateReport = async (
  id: string,
  body: { title?: string; description?: string; occurred_on?: string; expected_version: number },
) => (await apiRequest<{ report: Report }>(`/reports/${id}`, { method: "PATCH", json: body })).report;
export const moderatorCorrectReport = async (
  id: string,
  body: {
    title?: string | undefined;
    description?: string | undefined;
    occurred_on?: string | undefined;
    category_id?: string | undefined;
    location_id?: string | undefined;
    decision_note?: string | undefined;
    expected_version: number;
  },
) => (await post<{ report: Report }>(`/moderation/reports/${id}/correct`, body)).report;
export const withdrawReport = async (id: string, expected_version: number) =>
  (await post<{ report: Report }>(`/reports/${id}/withdraw`, { expected_version })).report;

export const uploadReportPhoto = (id: string, file: File) => {
  const form = new FormData();
  form.append("file", file);
  return apiRequest<unknown>(`/reports/${id}/photo`, { method: "POST", form });
};
export const deleteReportPhoto = (id: string) => apiRequestNoContent(`/reports/${id}/photo`, { method: "DELETE" });
/** Same-origin-credentialed image URL for <img>; the cookie authorises the stream. */
export const reportPhotoUrl = (id: string) => `${getApiBaseUrl()}/reports/${id}/photo`;

// ---- matches
export const listMatches = (id: string, signal?: AbortSignal) =>
  apiRequest<Page<MatchItem>>(`/reports/${id}/matches?page_size=20`, signal ? { signal } : {});
export const recalculateMatches = (id: string) => post<{ job_id: string; status: string }>(`/reports/${id}/matches/recalculate`, {});
export const dismissMatch = (matchId: string, reason_code: string, decision_note?: string) =>
  post<unknown>(`/moderation/matches/${matchId}/dismiss`, { reason_code, decision_note });

// ---- claims (claimant)
export const submitClaim = async (foundId: string, claim_statement: string, lost_report_id?: string) =>
  (await post<{ claim: Claim }>(`/reports/${foundId}/claims`, { claim_statement, lost_report_id: lost_report_id || null })).claim;
export const listMyClaims = (page = 1, signal?: AbortSignal) =>
  apiRequest<Page<Claim>>(`/me/claims${qs({ page, page_size: 20 })}`, signal ? { signal } : {});
export const getClaim = async (id: string, signal?: AbortSignal) => {
  const data = await apiRequest<{ claim: Claim }>(`/claims/${id}`, signal ? { signal } : {});
  return data.claim;
};
export const cancelClaim = async (id: string, expected_version: number) =>
  (await post<{ claim: Claim }>(`/claims/${id}/cancel`, { expected_version })).claim;
export const uploadEvidence = (id: string, files: File[]) => {
  const form = new FormData();
  for (const f of files) form.append("files[]", f);
  return apiRequest<unknown>(`/claims/${id}/evidence`, { method: "POST", form });
};
export const deleteEvidence = (claimId: string, evidenceId: string) =>
  apiRequestNoContent(`/claims/${claimId}/evidence/${evidenceId}`, { method: "DELETE" });
export const evidenceUrl = (claimId: string, evidenceId: string) => `${getApiBaseUrl()}/claims/${claimId}/evidence/${evidenceId}`;

export interface ModerationClaimSummary {
  claim_id: string;
  status: ClaimStatus;
  version: number;
  created_at_utc: string;
  status_changed_at_utc: string;
  claimant: { display_name: string };
  found_report: ReportRef;
  has_linked_lost_report: boolean;
  evidence_count: number;
}

// ---- moderation
export const listModerationClaims = (status: ClaimStatus | "", page: number, signal?: AbortSignal) =>
  apiRequest<Page<ModerationClaimSummary>>(
    `/moderation/claims${qs({ status, page, page_size: 20 })}`,
    signal ? { signal } : {},
  );
export const getModerationClaim = async (id: string, signal?: AbortSignal) => {
  const data = await apiRequest<{ claim: ModeratorClaim } | ModeratorClaim>(`/moderation/claims/${id}`, signal ? { signal } : {});
  return "claim" in data ? data.claim : data;
};

type ClaimAction = "verify" | "reject" | "revoke-verification" | "request-information";
export const claimAction = async (
  id: string,
  action: ClaimAction,
  body: { expected_version: number; decision_note?: string | undefined; reason_code?: string | undefined },
) => (await post<{ claim: Claim }>(`/moderation/claims/${id}/${action}`, body)).claim;
export const recoverClaim = (id: string, expected_version: number, decision_note?: string | undefined) =>
  post<{ claim: Claim; recovery: Recovery; resolved_reports: string[] }>(`/moderation/claims/${id}/recover`, {
    expected_version,
    ...(decision_note ? { decision_note } : {}),
  });
export const voidRecovery = (recoveryId: string, expected_claim_version: number, decision_note: string) =>
  post<{ claim: Claim; recovery: Recovery; reopened_reports: string[]; reports_requiring_reconciliation: string[] }>(
    `/moderation/recoveries/${recoveryId}/void`,
    { expected_claim_version, decision_note },
  );
export const closeReport = (id: string, reason_code: string, expected_version: number, decision_note?: string | undefined) =>
  post<{ report: Report }>(`/moderation/reports/${id}/close`, {
    reason_code,
    expected_version,
    ...(decision_note ? { decision_note } : {}),
  });
export const reopenReport = (id: string, expected_version: number, decision_note?: string | undefined) =>
  post<{ report: Report }>(`/moderation/reports/${id}/reopen`, {
    expected_version,
    ...(decision_note ? { decision_note } : {}),
  });

export const getAnalytics = (from: string, to: string, signal?: AbortSignal) =>
  apiRequest<Analytics>(`/moderation/analytics/summary${qs({ from, to })}`, signal ? { signal } : {});
export const listActivity = (page: number, signal?: AbortSignal) =>
  apiRequest<Page<ActivityItem>>(`/moderation/activity${qs({ page, page_size: 25 })}`, signal ? { signal } : {});

/** Moderator evidence removal (contract 4.4): reason must be OTHER or INSUFFICIENT_EVIDENCE. */
export const moderatorDeleteEvidence = (claimId: string, evidenceId: string, reason_code: string, decision_note?: string) =>
  apiRequestNoContent(`/moderation/claims/${claimId}/evidence/${evidenceId}`, {
    method: "DELETE",
    json: decision_note ? { reason_code, decision_note } : { reason_code },
  });
