"""Claim evidence upload/retrieval (contract A4.4, A9, A21, A24). Real SQL Server, real image fixtures, LocalBlobStore."""

from __future__ import annotations

import io
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from app.services.blobstore import BlobUnavailableError, LocalBlobStore, set_blob_store
from tests import image_fixtures as fx
from tests.api_helpers import login_api
from tests.helpers import make_claim, make_report

pytestmark = pytest.mark.sql

KEY_RE = re.compile(r"^attachments/[0-9a-f-]{36}\.(jpg|png|webp)$")


@pytest.fixture()
def app(db):
    from app.main import create_app

    return create_app()


@pytest.fixture()
def store(tmp_path):
    s = LocalBlobStore(str(tmp_path / "blobs"))
    set_blob_store(s)
    yield s
    set_blob_store(None)


class FlakyStore(LocalBlobStore):
    """Real directory store that fails on demand with the adapter's storage-outage error."""

    fail_put = False
    fail_get = False
    fail_delete = False
    fail_put_on_call: int | None = None  # 1-based index of the put() call that fails
    _puts = 0

    def put(self, key, data, content_type):
        self._puts += 1
        if self.fail_put or self.fail_put_on_call == self._puts:
            raise BlobUnavailableError
        super().put(key, data, content_type)

    def get(self, key):
        if self.fail_get:
            raise BlobUnavailableError
        return super().get(key)

    def delete(self, key):
        if self.fail_delete:
            raise BlobUnavailableError
        super().delete(key)


@pytest.fixture()
def flaky(tmp_path):
    s = FlakyStore(str(tmp_path / "flaky"))
    set_blob_store(s)
    yield s
    set_blob_store(None)


class Scene:
    """FOUND report (owner `finder`), claimant with a claim, report-unrelated student, moderator."""

    def __init__(self, app, db, status="PENDING"):
        self.app, self.db = app, db
        self.finder = login_api(app, db, name="Finder")
        self.claimant = login_api(app, db, name="Claimant")
        self.other = login_api(app, db, name="Other Student")
        self.mod = login_api(app, db, "MODERATOR", "Mod One")
        self.found = make_report(db, self.finder.user, "FOUND")
        self.claim = make_claim(db, self.claimant.user, self.found, status=status)
        db.commit()
        self.cid = self.claim.claim_id

    @property
    def url(self):
        return f"/api/claims/{self.cid}/evidence"

    def put(self, who, *blobs, name="proof.jpg", mime="image/jpeg"):
        files = [("files[]", (name, b, mime)) for b in blobs]
        return who.post(self.url, files=files)

    def rows(self):
        self.db.rollback()
        return self.db.execute(
            text("SELECT evidence_id, blob_key, content_type, size_bytes, upload_status, original_filename "
                 "FROM claim_evidence WHERE claim_id=:c ORDER BY uploaded_at_utc"), {"c": self.cid}).all()

    def claim_state(self):
        self.db.rollback()
        return self.db.execute(text("SELECT version, status, status_changed_at_utc FROM claims WHERE claim_id=:c"),
                               {"c": self.cid}).one()

    def audit(self, event):
        self.db.rollback()
        rows = self.db.execute(text("SELECT * FROM activity_logs WHERE event_type=:e"), {"e": event}).all()
        return rows, " ".join(str(c) for r in rows for c in r)


def seed(scene, store, data=None):
    """Upload one evidence image through the API as the claimant and return its id."""
    r = scene.put(scene.claimant, data or fx.jpeg_with_exif())
    assert r.status_code == 201, r.text
    return r.json()["evidence"][0]["evidence_id"]


def no_raise(api, app):
    api.http = TestClient(app, headers=api.http.headers, cookies=api.http.cookies, raise_server_exceptions=False)


# ------------------------------------------------------------------------------------------ upload success

@pytest.mark.parametrize("data,mime,name,ctype", [
    (fx.jpeg_with_exif(), "image/jpeg", "cam.jpg", "image/jpeg"),
    (fx.png_with_text(), "image/png", "shot.png", "image/png"),
    (fx.webp_with_exif(), "image/webp", "pic.webp", "image/webp"),
])
def test_upload_success_stores_random_key_reencodes_and_strips_metadata(app, db, store, data, mime, name, ctype):
    s = Scene(app, db)
    before = s.claim_state()
    r = s.put(s.claimant, data, name=name, mime=mime)
    assert r.status_code == 201, r.text
    ev = r.json()["evidence"]
    assert len(ev) == 1 and set(ev[0]) == {"evidence_id", "content_type", "size_bytes", "uploaded_at_utc"}
    assert ev[0]["content_type"] == ctype
    for leak in ("blob", "attachments/", "http", "sas", name):
        assert leak not in r.text.lower()
    (row,) = s.rows()
    assert KEY_RE.match(row.blob_key) and row.upload_status == "ACTIVE" and row.content_type == ctype
    stored = store.get(row.blob_key)
    assert row.size_bytes == len(stored) == ev[0]["size_bytes"]
    assert fx.MARKER.encode() not in stored  # EXIF / PNG text / JPEG comment gone
    img = Image.open(io.BytesIO(stored))
    assert not img.getexif() and fx.MARKER not in str(img.info)
    after = s.claim_state()
    assert after.version == before.version + 1  # bumped exactly once
    assert after.status == before.status and after.status_changed_at_utc == before.status_changed_at_utc
    rows, blob = s.audit("CLAIM_EVIDENCE_UPLOADED")
    assert len(rows) == 1 and name not in blob and row.blob_key not in blob and fx.MARKER not in blob


def test_multiple_files_in_one_request_bump_version_once(app, db, store):
    s = Scene(app, db)
    v = s.claim_state().version
    r = s.put(s.claimant, fx.jpeg_with_exif(), fx.png_with_text())
    assert r.status_code == 201 and len(r.json()["evidence"]) == 2
    assert len(s.rows()) == 2 and len(list(store.list())) == 2
    assert s.claim_state().version == v + 1


def test_verified_claim_accepts_evidence(app, db, store):
    s = Scene(app, db, status="VERIFIED")
    assert s.put(s.claimant, fx.jpeg_with_exif()).status_code == 201


def test_evidence_appears_in_claimant_dto_without_blob_key(app, db, store):
    s = Scene(app, db)
    ev_id = seed(s, store)
    c = s.claimant.get(f"/api/claims/{s.cid}").json()["claim"]
    assert [e["evidence_id"] for e in c["evidence"]] == [ev_id]
    assert "blob" not in str(c).lower() and "attachments/" not in str(c)
    m = s.mod.get(f"/api/moderation/claims/{s.cid}").json()["claim"]
    assert [e["evidence_id"] for e in m["evidence"]] == [ev_id] and "attachments/" not in str(m)


# ------------------------------------------------------------------------------------------ limits & validation

def test_fourth_image_total_is_rejected_with_409(app, db, store):
    s = Scene(app, db)
    assert s.put(s.claimant, fx.jpeg_with_exif(), fx.png_with_text()).status_code == 201
    assert s.put(s.claimant, fx.webp_with_exif()).status_code == 201
    v = s.claim_state().version
    r = s.put(s.claimant, fx.jpeg_with_exif())
    assert r.status_code == 409 and r.json()["error"]["code"] == "EVIDENCE_LIMIT_EXCEEDED"
    assert len(s.rows()) == 3 and len(list(store.list())) == 3 and s.claim_state().version == v


def test_four_files_in_one_request_rejected_and_nothing_stored(app, db, store):
    s = Scene(app, db)
    r = s.put(s.claimant, *[fx.jpeg_with_exif()] * 4)
    assert r.status_code == 409 and r.json()["error"]["code"] == "EVIDENCE_LIMIT_EXCEEDED"
    assert s.rows() == [] and list(store.list()) == []


def test_two_plus_two_is_rejected_atomically(app, db, store):
    s = Scene(app, db)
    assert s.put(s.claimant, fx.jpeg_with_exif(), fx.png_with_text()).status_code == 201
    r = s.put(s.claimant, fx.jpeg_with_exif(), fx.webp_with_exif())
    assert r.status_code == 409
    assert len(s.rows()) == 2 and len(list(store.list())) == 2


@pytest.mark.parametrize("data,status,code", [
    (fx.NOT_AN_IMAGE, 422, "INVALID_IMAGE"),
    (fx.truncated_jpeg(), 422, "INVALID_IMAGE"),
    (b"", 422, "INVALID_IMAGE"),
    (fx.gif_static(), 415, "UNSUPPORTED_MEDIA_TYPE"),
    (fx.bmp(), 415, "UNSUPPORTED_MEDIA_TYPE"),
    (fx.oversized_png(), 413, "PAYLOAD_TOO_LARGE"),
])
def test_invalid_images_rejected_with_no_side_effects(app, db, store, data, status, code):
    s = Scene(app, db)
    v = s.claim_state().version
    r = s.put(s.claimant, data)
    assert r.status_code == status and r.json()["error"]["code"] == code, r.text
    assert s.rows() == [] and list(store.list()) == [] and s.claim_state().version == v
    assert s.audit("CLAIM_EVIDENCE_UPLOADED")[0] == []


def test_one_bad_file_rejects_whole_batch(app, db, store):
    s = Scene(app, db)
    r = s.put(s.claimant, fx.jpeg_with_exif(), fx.NOT_AN_IMAGE)
    assert r.status_code == 422
    assert s.rows() == [] and list(store.list()) == []


def test_missing_files_field_is_validation_error(app, db, store):
    s = Scene(app, db)
    r = s.claimant.post(s.url, data={"x": "y"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("status", ["REJECTED", "CANCELLED", "RECOVERED"])
def test_terminal_claim_rejects_upload(app, db, store, status):
    s = Scene(app, db, status=status)
    r = s.put(s.claimant, fx.jpeg_with_exif())
    assert r.status_code == 409 and r.json()["error"]["code"] == "CLAIM_NOT_ACTIVE"
    assert s.rows() == [] and list(store.list()) == []


# ------------------------------------------------------------------------------------------ upload authorization

def test_upload_denied_for_moderator_report_owner_unrelated_and_anonymous(app, db, store):
    s = Scene(app, db)
    assert s.put(s.mod, fx.jpeg_with_exif()).status_code == 403
    for who in (s.finder, s.other):  # concealment: the claim's existence is not revealed
        r = s.put(who, fx.jpeg_with_exif())
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    anon = TestClient(app, headers={"Origin": "http://localhost:5173"})
    r = anon.post(s.url, files=[("files[]", ("a.jpg", fx.jpeg_with_exif(), "image/jpeg"))])
    assert r.status_code == 401
    assert s.rows() == [] and list(store.list()) == []


def test_upload_to_unknown_claim_is_404(app, db, store):
    s = Scene(app, db)
    r = s.claimant.post(f"/api/claims/{uuid.uuid4()}/evidence", files=[("files[]", ("a.jpg", fx.jpeg_with_exif(), "image/jpeg"))])
    assert r.status_code == 404


# ------------------------------------------------------------------------------------------ retrieval

def test_claimant_retrieves_own_evidence_with_private_headers(app, db, store):
    s = Scene(app, db)
    ev_id = seed(s, store, fx.png_with_text())
    r = s.claimant.get(f"{s.url}/{ev_id}")
    assert r.status_code == 200
    (row,) = s.rows()
    assert r.content == store.get(row.blob_key) and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "private, no-store" and r.headers["x-content-type-options"] == "nosniff"
    cd = r.headers["content-disposition"]
    assert cd.startswith("inline;") and "proof" not in cd and row.blob_key.split("/")[-1].split(".")[0] not in cd
    assert fx.MARKER.encode() not in r.content
    assert s.audit("MODERATOR_EVIDENCE_ACCESSED")[0] == []  # claimant access is not a moderator access


def test_moderator_retrieves_evidence_and_access_is_audited(app, db, store):
    s = Scene(app, db)
    ev_id = seed(s, store)
    r = s.mod.get(f"{s.url}/{ev_id}")
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    rows, blob = s.audit("MODERATOR_EVIDENCE_ACCESSED")
    assert len(rows) == 1 and str(s.cid) in blob and "attachments/" not in blob
    assert s.mod.get(f"{s.url}/{ev_id}").status_code == 200
    assert len(s.audit("MODERATOR_EVIDENCE_ACCESSED")[0]) == 2  # every access


def test_report_owner_and_unrelated_student_never_receive_evidence(app, db, store):
    s = Scene(app, db)
    ev_id = seed(s, store)
    for who in (s.finder, s.other):
        r = who.get(f"{s.url}/{ev_id}")
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
        assert r.headers["content-type"].startswith("application/json")
    anon = TestClient(app, headers={"Origin": "http://localhost:5173"})
    assert anon.get(f"{s.url}/{ev_id}").status_code == 401
    assert s.audit("MODERATOR_EVIDENCE_ACCESSED")[0] == []


def test_other_claimant_cannot_read_evidence_of_a_different_claim(app, db, store):
    s = Scene(app, db)
    ev_id = seed(s, store)
    second = make_claim(db, s.other.user, s.found)
    db.commit()
    assert s.other.get(f"/api/claims/{second.claim_id}/evidence/{ev_id}").status_code == 404  # id belongs to another claim
    assert s.mod.get(f"/api/claims/{second.claim_id}/evidence/{ev_id}").status_code == 404
    assert s.other.get(f"{s.url}/{ev_id}").status_code == 404


def test_unknown_or_deleted_evidence_is_404(app, db, store):
    s = Scene(app, db)
    ev_id = seed(s, store)
    assert s.claimant.get(f"{s.url}/{uuid.uuid4()}").status_code == 404
    assert s.claimant.get(f"/api/claims/{uuid.uuid4()}/evidence/{ev_id}").status_code == 404
    assert s.claimant.delete(f"{s.url}/{ev_id}").status_code == 204
    assert s.claimant.get(f"{s.url}/{ev_id}").status_code == 404
    assert s.mod.get(f"{s.url}/{ev_id}").status_code == 404


def test_missing_blob_returns_404_not_500(app, db, store):
    s = Scene(app, db)
    ev_id = seed(s, store)
    (row,) = s.rows()
    store.delete(row.blob_key)
    r = s.claimant.get(f"{s.url}/{ev_id}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_storage_outage_on_retrieval_is_503_and_not_audited(app, db, flaky):
    s = Scene(app, db)
    ev_id = seed(s, flaky)
    flaky.fail_get = True
    assert s.claimant.get(f"{s.url}/{ev_id}").status_code == 503
    r = s.mod.get(f"{s.url}/{ev_id}")
    assert r.status_code == 503 and r.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert s.audit("MODERATOR_EVIDENCE_ACCESSED")[0] == []  # nothing was delivered, so nothing is logged as accessed
    flaky.fail_get = False
    assert s.claimant.get(f"{s.url}/{ev_id}").status_code == 200


# ------------------------------------------------------------------------------------------ storage failures & DB consistency

def test_storage_failure_on_upload_is_503_and_leaves_no_metadata(app, db, flaky):
    s = Scene(app, db)
    v = s.claim_state().version
    flaky.fail_put = True
    r = s.put(s.claimant, fx.jpeg_with_exif())
    assert r.status_code == 503 and r.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert s.rows() == [] and list(flaky.list()) == [] and s.claim_state().version == v
    assert s.audit("CLAIM_EVIDENCE_UPLOADED")[0] == []
    flaky.fail_put = False
    assert s.put(s.claimant, fx.jpeg_with_exif()).status_code == 201  # retry works


def test_partial_storage_failure_removes_blobs_already_written(app, db, flaky):
    s = Scene(app, db)
    flaky.fail_put_on_call = 2
    r = s.put(s.claimant, fx.jpeg_with_exif(), fx.png_with_text(), fx.webp_with_exif())
    assert r.status_code == 503
    assert list(flaky.list()) == [] and s.rows() == []


def test_sql_failure_after_blob_write_removes_blobs_and_rolls_back(app, db, store, monkeypatch):
    from app.services import audit

    s = Scene(app, db)
    v = s.claim_state().version

    def boom(*a, **k):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(audit, "log_event", boom)
    no_raise(s.claimant, app)
    assert s.put(s.claimant, fx.jpeg_with_exif(), fx.png_with_text()).status_code == 500
    assert list(store.list()) == [] and s.rows() == [] and s.claim_state().version == v


def test_db_rows_match_blobs_exactly_after_mixed_operations(app, db, store):
    s = Scene(app, db)
    s.put(s.claimant, fx.jpeg_with_exif(), fx.png_with_text())
    s.put(s.claimant, fx.NOT_AN_IMAGE)  # rejected
    s.put(s.claimant, fx.webp_with_exif())
    s.put(s.claimant, fx.jpeg_with_exif())  # 4th: rejected
    active = {r.blob_key for r in s.rows() if r.upload_status == "ACTIVE"}
    assert len(active) == 3 and {b.key for b in store.list()} == active
    assert all(KEY_RE.match(k) for k in active) and len(active) == len({r.blob_key for r in s.rows()})


# ------------------------------------------------------------------------------------------ deletion (shares the same storage path)

def test_claimant_delete_removes_blob_then_marks_metadata_and_allows_new_upload(app, db, store):
    s = Scene(app, db)
    ids = [e["evidence_id"] for e in s.put(s.claimant, *[fx.jpeg_with_exif()] * 3).json()["evidence"]]
    v = s.claim_state().version
    assert s.claimant.delete(f"{s.url}/{ids[0]}").status_code == 204
    assert sorted(r.upload_status for r in s.rows()) == ["ACTIVE", "ACTIVE", "DELETED"] and len(list(store.list())) == 2
    assert s.claim_state().version == v + 1
    assert s.put(s.claimant, fx.png_with_text()).status_code == 201  # slot freed
    assert s.audit("CLAIM_EVIDENCE_DELETED")[0]


def test_delete_authorization(app, db, store):
    s = Scene(app, db)
    ev_id = seed(s, store)
    assert s.mod.delete(f"{s.url}/{ev_id}").status_code == 403
    assert s.finder.delete(f"{s.url}/{ev_id}").status_code == 404
    assert s.other.delete(f"{s.url}/{ev_id}").status_code == 404
    assert [r.upload_status for r in s.rows()] == ["ACTIVE"]


def test_blob_delete_failure_is_503_and_metadata_retained(app, db, flaky):
    s = Scene(app, db)
    ev_id = seed(s, flaky)
    flaky.fail_delete = True
    r = s.claimant.delete(f"{s.url}/{ev_id}")
    assert r.status_code == 503
    assert [r.upload_status for r in s.rows()] == ["ACTIVE"] and len(list(flaky.list())) == 1
    flaky.fail_delete = False
    assert s.claimant.delete(f"{s.url}/{ev_id}").status_code == 204


def test_moderator_delete_requires_valid_reason_and_is_audited(app, db, store):
    s = Scene(app, db)
    ev_id = seed(s, store)
    url = f"/api/moderation/claims/{s.cid}/evidence/{ev_id}"
    assert s.mod.delete_json(url, {"reason_code": "BOGUS"}).status_code == 422
    assert s.mod.delete_json(url, {"reason_code": "OTHER"}).status_code == 422  # note required
    assert s.other.delete_json(url, {"reason_code": "INSUFFICIENT_EVIDENCE"}).status_code == 403
    assert s.mod.delete_json(url, {"reason_code": "INSUFFICIENT_EVIDENCE"}).status_code == 204
    assert [r.upload_status for r in s.rows()] == ["DELETED"] and list(store.list()) == []
    assert s.audit("CLAIM_EVIDENCE_DELETED")[0]
