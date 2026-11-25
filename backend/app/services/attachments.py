"""Report photo and claim evidence services (contract A4.2, A4.4, A9, A21, A24).

Rules enforced here:
- Images are decoded and re-encoded by `process_image` (EXIF/metadata stripped); raw bytes are never stored.
- Blob keys are server-generated (`attachments/<uuid4>.<ext>`); keys, SAS URLs and filenames never leave the server.
- Uploads: process -> lock -> re-check -> Blob put -> metadata insert. Any failure removes Blobs written by the request.
- Deletes: Blob delete first (404 = success), then metadata is soft-deleted. A Blob failure -> 503, metadata retained.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict, forbidden, not_found, unavailable, unprocessable
from app.core.security import new_id, utcnow
from app.core.text import clean_optional_note
from app.persistence.models import Attachment, Claim, ClaimEvidence
from app.services import audit
from app.services.auth import AuthContext
from app.services.blobstore import BlobNotFoundError, BlobStore, BlobUnavailableError, get_blob_store
from app.services.claims import LIVE, _load_claim
from app.services.images import ProcessedImage, process_image, safe_original_filename
from app.services.locking import lock_claims, lock_reports
from app.services.reports import get_visible_report, iso

MAX_EVIDENCE = 3
PHOTO_TYPE = "REPORT_PHOTO"
MODERATOR_EVIDENCE_REASONS = {"OTHER", "INSUFFICIENT_EVIDENCE"}


@dataclass(frozen=True)
class StoredFile:
    data: bytes
    content_type: str
    extension: str


@dataclass(frozen=True)
class RawUpload:
    data: bytes
    filename: str | None


def _storage() -> BlobStore:
    return get_blob_store()


def _new_key(ext: str) -> str:
    return f"attachments/{uuid.uuid4()}.{ext}"


def _put_all(store: BlobStore, items: list[tuple[str, ProcessedImage]]) -> list[str]:
    """Upload every processed image; on any failure remove what this request already wrote, then raise 503."""
    written: list[str] = []
    try:
        for key, img in items:
            store.put(key, img.data, img.content_type)
            written.append(key)
    except BlobUnavailableError:
        _discard(store, written)
        raise unavailable("File storage is temporarily unavailable.") from None
    return written


def _discard(store: BlobStore, keys: list[str]) -> None:
    for key in keys:
        try:
            store.delete(key)
        except BlobUnavailableError:
            pass  # the 24 h orphan sweep removes it; the original error is what the caller reports


def _delete_blob(store: BlobStore, key: str) -> None:
    try:
        store.delete(key)
    except BlobUnavailableError:
        raise unavailable("File storage is temporarily unavailable; nothing was deleted. Please retry.") from None


def _read_blob(store: BlobStore, key: str, what: str) -> bytes:
    try:
        return store.get(key)
    except BlobNotFoundError:
        raise not_found(f"{what} not found.") from None
    except BlobUnavailableError:
        raise unavailable("File storage is temporarily unavailable.") from None


# ------------------------------------------------------------------------------ report photo

def _active_photo(db: Session, report_id: uuid.UUID) -> Attachment | None:
    return db.scalars(
        select(Attachment).where(
            Attachment.report_id == report_id, Attachment.attachment_type == PHOTO_TYPE,
            Attachment.upload_status == "ACTIVE", Attachment.deleted_at_utc.is_(None),
        )
    ).first()


def upload_report_photo(db: Session, ctx: AuthContext, report_id: uuid.UUID, upload: RawUpload, corr: str) -> dict:
    report = get_visible_report(db, ctx, report_id)
    if report.reporter_user_id != ctx.user.user_id:
        raise forbidden("Only the report owner can upload a photo.")
    processed = process_image(upload.data)  # before taking any lock; raises 413/415/422
    locked = lock_reports(db, [report_id]).get(report_id)
    if locked is None:
        raise not_found("Report not found.")
    if locked.status not in ("ACTIVE", "RESOLVED"):
        raise conflict("REPORT_NOT_ACTIVE", "Photos can only be added to ACTIVE or RESOLVED reports.")
    if _active_photo(db, report_id) is not None:
        raise conflict("PHOTO_ALREADY_EXISTS", "This report already has a photo. Delete it first to replace it.")
    store = _storage()
    key = _new_key(processed.extension)
    written = _put_all(store, [(key, processed)])
    now = utcnow()
    row = Attachment(
        attachment_id=new_id(), report_id=report_id, uploaded_by_user_id=ctx.user.user_id, attachment_type=PHOTO_TYPE,
        blob_key=key, original_filename=safe_original_filename(upload.filename), content_type=processed.content_type,
        size_bytes=len(processed.data), upload_status="ACTIVE", created_at_utc=now,
    )
    try:
        db.add(row)
        db.flush()
        audit.log_event(db, event_type="REPORT_PHOTO_UPLOADED", outcome="SUCCESS", correlation_id=corr,
                        actor_user_id=ctx.user.user_id, target_type="REPORT", target_id=report_id)
    except IntegrityError:
        _discard(store, written)
        raise conflict("PHOTO_ALREADY_EXISTS", "This report already has a photo. Delete it first to replace it.") from None
    except Exception:
        _discard(store, written)
        raise
    return {"attachment": {"attachment_id": str(row.attachment_id), "content_type": row.content_type,
                           "size_bytes": row.size_bytes, "created_at_utc": iso(row.created_at_utc)}}


def get_report_photo(db: Session, ctx: AuthContext, report_id: uuid.UUID) -> StoredFile:
    get_visible_report(db, ctx, report_id)
    att = _active_photo(db, report_id)
    if att is None:
        raise not_found("This report has no photo.")
    data = _read_blob(_storage(), att.blob_key, "Photo")
    return StoredFile(data, att.content_type, att.blob_key.rsplit(".", 1)[-1])


def delete_report_photo(db: Session, ctx: AuthContext, report_id: uuid.UUID, corr: str) -> None:
    report = get_visible_report(db, ctx, report_id)
    if not ctx.is_moderator and report.reporter_user_id != ctx.user.user_id:
        raise forbidden("Only the report owner or a moderator can delete the photo.")
    lock_reports(db, [report_id])
    att = _active_photo(db, report_id)
    if att is None:
        raise not_found("This report has no photo.")
    _delete_blob(_storage(), att.blob_key)
    att.upload_status, att.deleted_at_utc = "DELETED", utcnow()
    db.flush()
    audit.log_event(db, event_type="REPORT_PHOTO_DELETED", outcome="SUCCESS", correlation_id=corr,
                    actor_user_id=ctx.user.user_id, target_type="REPORT", target_id=report_id,
                    metadata={"role": ctx.role})


# ---------------------------------------------------------------------------- claim evidence

def _active_evidence(db: Session, claim_id: uuid.UUID) -> list[ClaimEvidence]:
    return list(db.scalars(
        select(ClaimEvidence).where(
            ClaimEvidence.claim_id == claim_id, ClaimEvidence.upload_status == "ACTIVE", ClaimEvidence.deleted_at_utc.is_(None),
        ).order_by(ClaimEvidence.uploaded_at_utc, ClaimEvidence.evidence_id)
    ))


def _evidence_dto(e: ClaimEvidence) -> dict:
    return {"evidence_id": str(e.evidence_id), "content_type": e.content_type, "size_bytes": e.size_bytes,
            "uploaded_at_utc": iso(e.uploaded_at_utc)}


def _own_claim(db: Session, ctx: AuthContext, claim_id: uuid.UUID) -> Claim:
    c = _load_claim(db, claim_id)
    if c.claimant_user_id != ctx.user.user_id:
        raise not_found("Claim not found.")  # concealment: other students never learn the claim exists
    return c


def _lock_claim(db: Session, claim_id: uuid.UUID) -> Claim:
    locked = lock_claims(db, [claim_id]).get(claim_id)
    if locked is None:
        raise not_found("Claim not found.")
    return locked


def _bump_claim(c: Claim) -> None:
    c.version, c.updated_at_utc = c.version + 1, utcnow()  # status and status_changed_at_utc are untouched


def upload_claim_evidence(db: Session, ctx: AuthContext, claim_id: uuid.UUID, uploads: list[RawUpload], corr: str) -> dict:
    if ctx.role != "STUDENT":
        raise forbidden("Only the claimant can upload evidence.")
    _own_claim(db, ctx, claim_id)
    if not uploads:
        raise unprocessable("No files supplied.", {"files[]": ["At least one image is required."]})
    if len(uploads) > MAX_EVIDENCE:
        raise conflict("EVIDENCE_LIMIT_EXCEEDED", f"A claim can have at most {MAX_EVIDENCE} evidence images.")
    processed = [process_image(u.data) for u in uploads]  # all-or-nothing validation, before any lock
    c = _lock_claim(db, claim_id)
    if c.status not in LIVE:
        raise conflict("CLAIM_NOT_ACTIVE", "Evidence can only be added to PENDING or VERIFIED claims.")
    if len(_active_evidence(db, claim_id)) + len(processed) > MAX_EVIDENCE:
        raise conflict("EVIDENCE_LIMIT_EXCEEDED", f"A claim can have at most {MAX_EVIDENCE} evidence images in total.")
    store = _storage()
    keyed = [(_new_key(p.extension), p) for p in processed]
    written = _put_all(store, keyed)
    now = utcnow()
    rows = [
        ClaimEvidence(
            evidence_id=new_id(), claim_id=claim_id, uploaded_by_user_id=ctx.user.user_id, blob_key=key,
            original_filename=safe_original_filename(u.filename), content_type=p.content_type, size_bytes=len(p.data),
            upload_status="ACTIVE", uploaded_at_utc=now,
        )
        for (key, p), u in zip(keyed, uploads, strict=True)
    ]
    try:
        db.add_all(rows)
        _bump_claim(c)
        db.flush()
        for _ in rows:
            audit.log_event(db, event_type="CLAIM_EVIDENCE_UPLOADED", outcome="SUCCESS", correlation_id=corr,
                            actor_user_id=ctx.user.user_id, target_type="CLAIM", target_id=claim_id,
                            metadata={"claim_id": claim_id})
    except Exception:
        _discard(store, written)
        raise
    return {"evidence": [_evidence_dto(r) for r in rows]}


def get_claim_evidence(db: Session, ctx: AuthContext, claim_id: uuid.UUID, evidence_id: uuid.UUID, corr: str) -> StoredFile:
    c = _load_claim(db, claim_id)
    if not ctx.is_moderator and c.claimant_user_id != ctx.user.user_id:
        raise not_found("Evidence not found.")
    ev = db.get(ClaimEvidence, evidence_id)
    if ev is None or ev.claim_id != claim_id or ev.upload_status != "ACTIVE" or ev.deleted_at_utc is not None:
        raise not_found("Evidence not found.")
    data = _read_blob(_storage(), ev.blob_key, "Evidence")
    if ctx.is_moderator:
        audit.log_event(db, event_type="MODERATOR_EVIDENCE_ACCESSED", outcome="SUCCESS", correlation_id=corr,
                        actor_user_id=ctx.user.user_id, target_type="CLAIM", target_id=claim_id,
                        metadata={"claim_id": claim_id})
    return StoredFile(data, ev.content_type, ev.blob_key.rsplit(".", 1)[-1])


def _remove_evidence(db: Session, c: Claim, evidence_id: uuid.UUID) -> ClaimEvidence:
    ev = db.get(ClaimEvidence, evidence_id)
    if ev is None or ev.claim_id != c.claim_id or ev.upload_status != "ACTIVE" or ev.deleted_at_utc is not None:
        raise not_found("Evidence not found.")
    _delete_blob(_storage(), ev.blob_key)
    ev.upload_status, ev.deleted_at_utc = "DELETED", utcnow()
    _bump_claim(c)
    db.flush()
    return ev


def delete_own_evidence(db: Session, ctx: AuthContext, claim_id: uuid.UUID, evidence_id: uuid.UUID, corr: str) -> None:
    if ctx.role != "STUDENT":
        raise forbidden("Only the claimant can delete evidence.")
    _own_claim(db, ctx, claim_id)
    c = _lock_claim(db, claim_id)
    if c.status not in LIVE:
        raise conflict("CLAIM_NOT_ACTIVE", "Evidence can only be deleted while the claim is PENDING or VERIFIED.")
    _remove_evidence(db, c, evidence_id)
    audit.log_event(db, event_type="CLAIM_EVIDENCE_DELETED", outcome="SUCCESS", correlation_id=corr,
                    actor_user_id=ctx.user.user_id, target_type="CLAIM", target_id=claim_id,
                    metadata={"claim_id": claim_id, "role": ctx.role})


def moderator_delete_evidence(db: Session, ctx: AuthContext, claim_id: uuid.UUID, evidence_id: uuid.UUID, *, reason_code: str,
                              decision_note: str | None, corr: str) -> None:
    if reason_code not in MODERATOR_EVIDENCE_REASONS:
        raise unprocessable("Invalid reason.", {"reason_code": ["Must be OTHER or INSUFFICIENT_EVIDENCE."]})
    note = clean_optional_note(decision_note)
    if reason_code == "OTHER" and not note:
        raise unprocessable("A note is required.", {"decision_note": ["Required when the reason is OTHER."]})
    _load_claim(db, claim_id)
    c = _lock_claim(db, claim_id)
    _remove_evidence(db, c, evidence_id)
    audit.log_event(db, event_type="CLAIM_EVIDENCE_DELETED", outcome="SUCCESS", correlation_id=corr,
                    actor_user_id=ctx.user.user_id, target_type="CLAIM", target_id=claim_id,
                    metadata={"claim_id": claim_id, "reason_code": reason_code, "role": ctx.role})
