"""Report photo upload (contract A4.2, A9, A21, A24). Real SQL Server, real image fixtures, LocalBlobStore."""

from __future__ import annotations

import io
import re

import pytest
from PIL import Image
from sqlalchemy import text

from app.services.blobstore import BlobUnavailableError, LocalBlobStore, set_blob_store
from tests import image_fixtures as fx
from tests.api_helpers import login_api
from tests.helpers import make_report

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


class FailingStore(LocalBlobStore):
    """Delegates to a real directory store but fails on demand with the adapter's storage-outage error."""

    fail_put = False
    fail_delete = False

    def put(self, key, data, content_type):
        if self.fail_put:
            raise BlobUnavailableError
        super().put(key, data, content_type)

    def delete(self, key):
        if self.fail_delete:
            raise BlobUnavailableError
        super().delete(key)


@pytest.fixture()
def flaky(tmp_path):
    s = FailingStore(str(tmp_path / "flaky"))
    set_blob_store(s)
    yield s
    set_blob_store(None)


def owner_report(app, db, rtype="FOUND"):
    owner = login_api(app, db, name="Owner")
    report = make_report(db, owner.user, rtype)
    db.commit()
    return owner, report


def upload(api, report, data, name="photo.jpg", mime="image/jpeg"):
    return api.post(f"/api/reports/{report.report_id}/photo", files={"file": (name, data, mime)})


def attachment_rows(db, report):
    return db.execute(text("SELECT blob_key, content_type, size_bytes, upload_status, original_filename FROM attachments WHERE report_id=:r"),
                      {"r": report.report_id}).all()


def audit_text(db, event):
    rows = db.execute(text("SELECT * FROM activity_logs WHERE event_type=:e"), {"e": event}).all()
    return rows, " ".join(str(c) for row in rows for c in row)


# ------------------------------------------------------------------------------------------ success

@pytest.mark.parametrize("data,mime,name,ctype,ext", [
    (fx.jpeg_with_exif(), "image/jpeg", "cam.jpg", "image/jpeg", "jpg"),
    (fx.png_with_text(), "image/png", "shot.png", "image/png", "png"),
    (fx.webp_with_exif(), "image/webp", "pic.webp", "image/webp", "webp"),
])
def test_upload_success_stores_random_key_and_metadata(app, db, store, data, mime, name, ctype, ext):
    owner, report = owner_report(app, db)
    r = upload(owner, report, data, name, mime)
    assert r.status_code == 201, r.text
    att = r.json()["attachment"]
    assert set(att) == {"attachment_id", "content_type", "size_bytes", "created_at_utc"} and att["content_type"] == ctype
    assert not re.search(r"blob|sas|https?://|attachments/", r.text)  # no key, URL or container ever leaves the server
    (row,) = attachment_rows(db, report)
    assert KEY_RE.match(row.blob_key) and row.blob_key.endswith(f".{ext}") and name.split(".")[0] not in row.blob_key
    assert (row.content_type, row.upload_status, row.size_bytes) == (ctype, "ACTIVE", att["size_bytes"])
    assert len(store.get(row.blob_key)) == row.size_bytes
    rows, text_ = audit_text(db, "REPORT_PHOTO_UPLOADED")
    assert len(rows) == 1 and name not in text_ and row.blob_key not in text_ and fx.MARKER not in text_


def test_upload_then_authorized_get_has_private_headers(app, db, store):
    owner, report = owner_report(app, db)
    upload(owner, report, fx.jpeg_with_exif())
    other = login_api(app, db, name="Other Student")
    for viewer in (owner, other):
        g = viewer.get(f"/api/reports/{report.report_id}/photo")
        assert g.status_code == 200 and g.headers["content-type"] == "image/jpeg"
        assert g.headers["cache-control"] == "private, no-store" and g.headers["x-content-type-options"] == "nosniff"
        assert g.headers["content-disposition"] == 'inline; filename="report-photo.jpg"'
        assert Image.open(io.BytesIO(g.content)).format == "JPEG"


def test_second_upload_conflicts_until_deleted(app, db, store):
    owner, report = owner_report(app, db)
    assert upload(owner, report, fx.jpeg_with_exif()).status_code == 201
    dup = upload(owner, report, fx.png_with_text(), "b.png", "image/png")
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "PHOTO_ALREADY_EXISTS"
    assert len(list(store.list())) == 1  # the rejected request wrote nothing
    assert owner.delete(f"/api/reports/{report.report_id}/photo").status_code == 204
    assert upload(owner, report, fx.png_with_text(), "b.png", "image/png").status_code == 201


def test_upload_to_withdrawn_report_is_rejected(app, db, store):
    owner = login_api(app, db, name="Owner")
    report = make_report(db, owner.user, "LOST", status="WITHDRAWN")
    db.commit()
    r = upload(owner, report, fx.jpeg_with_exif())
    assert r.status_code == 409 and r.json()["error"]["code"] == "REPORT_NOT_ACTIVE"
    assert attachment_rows(db, report) == [] and list(store.list()) == []


# ------------------------------------------------------------------------- invalid / unsupported / big

@pytest.mark.parametrize("data", [fx.NOT_AN_IMAGE, fx.truncated_jpeg(), b""])
def test_invalid_image_is_rejected_and_nothing_stored(app, db, store, data):
    owner, report = owner_report(app, db)
    r = upload(owner, report, data, "evil.jpg", "image/jpeg")  # lying filename and MIME type
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_IMAGE"
    assert attachment_rows(db, report) == [] and list(store.list()) == []
    assert audit_text(db, "REPORT_PHOTO_UPLOADED")[0] == []


@pytest.mark.parametrize("data,name,mime", [
    (fx.gif_static(), "a.gif", "image/gif"), (fx.bmp(), "a.bmp", "image/bmp"),
    (fx.gif_static(), "renamed.jpg", "image/jpeg"),  # content decides, not the declared type
])
def test_unsupported_format_is_415(app, db, store, data, name, mime):
    owner, report = owner_report(app, db)
    r = upload(owner, report, data, name, mime)
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert attachment_rows(db, report) == [] and list(store.list()) == []


def test_oversized_image_is_413_before_any_storage(app, db, store):
    owner, report = owner_report(app, db)
    r = upload(owner, report, fx.oversized_png(), "big.png", "image/png")
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert attachment_rows(db, report) == [] and list(store.list()) == []


def test_missing_file_field_is_validation_error(app, db, store):
    owner, report = owner_report(app, db)
    r = owner.post(f"/api/reports/{report.report_id}/photo", files={"wrong": ("a.jpg", fx.jpeg_with_exif(), "image/jpeg")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


# ------------------------------------------------------------------------ authorization / ownership

def test_anonymous_upload_is_401(app, db, store):
    from fastapi.testclient import TestClient

    from tests.api_helpers import ORIGIN

    _, report = owner_report(app, db)
    r = TestClient(app, headers={"Origin": ORIGIN}).post(
        f"/api/reports/{report.report_id}/photo", files={"file": ("a.jpg", fx.jpeg_with_exif(), "image/jpeg")})
    assert r.status_code == 401 and list(store.list()) == []


def test_upload_requires_csrf_token(app, db, store):
    owner, report = owner_report(app, db)
    r = owner.http.post(f"/api/reports/{report.report_id}/photo", files={"file": ("a.jpg", fx.jpeg_with_exif(), "image/jpeg")})
    assert r.status_code in (400, 403) and list(store.list()) == []


@pytest.mark.parametrize("role", ["STUDENT", "MODERATOR"])
def test_only_the_report_owner_may_upload(app, db, store, role):
    _, report = owner_report(app, db)
    intruder = login_api(app, db, role, "Intruder")
    r = upload(intruder, report, fx.jpeg_with_exif())
    assert r.status_code == 403
    assert attachment_rows(db, report) == [] and list(store.list()) == []


def test_upload_to_unknown_report_is_404(app, db, store):
    import uuid

    owner = login_api(app, db)
    r = owner.post(f"/api/reports/{uuid.uuid4()}/photo", files={"file": ("a.jpg", fx.jpeg_with_exif(), "image/jpeg")})
    assert r.status_code == 404


def test_delete_allowed_for_owner_and_moderator_only(app, db, store):
    owner, report = owner_report(app, db)
    upload(owner, report, fx.jpeg_with_exif())
    stranger = login_api(app, db, name="Stranger")
    assert stranger.delete(f"/api/reports/{report.report_id}/photo").status_code == 403
    assert len(list(store.list())) == 1
    mod = login_api(app, db, "MODERATOR", "Mod")
    assert mod.delete(f"/api/reports/{report.report_id}/photo").status_code == 204
    assert list(store.list()) == []
    (row,) = attachment_rows(db, report)
    assert row.upload_status == "DELETED"
    assert len(audit_text(db, "REPORT_PHOTO_DELETED")[0]) == 1
    assert owner.get(f"/api/reports/{report.report_id}/photo").status_code == 404


# ----------------------------------------------------------------------------------- storage failure

def test_storage_failure_on_upload_returns_503_and_leaves_no_metadata(app, db, flaky):
    owner, report = owner_report(app, db)
    flaky.fail_put = True
    r = upload(owner, report, fx.jpeg_with_exif())
    assert r.status_code == 503 and r.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert attachment_rows(db, report) == [] and list(flaky.list()) == []
    assert audit_text(db, "REPORT_PHOTO_UPLOADED")[0] == []
    flaky.fail_put = False
    assert upload(owner, report, fx.jpeg_with_exif()).status_code == 201  # report is still usable; retry works


def test_sql_failure_after_blob_write_removes_the_blob(app, db, store, monkeypatch):
    from app.services import audit

    owner, report = owner_report(app, db)

    def boom(*a, **k):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(audit, "log_event", boom)
    from fastapi.testclient import TestClient

    owner.http = TestClient(app, headers=owner.http.headers, cookies=owner.http.cookies, raise_server_exceptions=False)
    assert upload(owner, report, fx.jpeg_with_exif()).status_code == 500
    assert list(store.list()) == [] and attachment_rows(db, report) == []  # compensating delete + rollback


def test_storage_failure_on_delete_returns_503_and_retains_metadata(app, db, flaky):
    owner, report = owner_report(app, db)
    assert upload(owner, report, fx.jpeg_with_exif()).status_code == 201
    flaky.fail_delete = True
    r = owner.delete(f"/api/reports/{report.report_id}/photo")
    assert r.status_code == 503
    (row,) = attachment_rows(db, report)
    assert row.upload_status == "ACTIVE" and len(list(flaky.list())) == 1
    assert audit_text(db, "REPORT_PHOTO_DELETED")[0] == []
    flaky.fail_delete = False
    assert owner.delete(f"/api/reports/{report.report_id}/photo").status_code == 204


def test_get_when_blob_is_missing_returns_404(app, db, flaky):
    owner, report = owner_report(app, db)
    upload(owner, report, fx.jpeg_with_exif())
    (row,) = attachment_rows(db, report)
    flaky.delete(row.blob_key)
    assert owner.get(f"/api/reports/{report.report_id}/photo").status_code == 404


# ---------------------------------------------------------------------------------- metadata stripping

def stored_image(db, store, report):
    (row,) = attachment_rows(db, report)
    raw = store.get(row.blob_key)
    return raw, Image.open(io.BytesIO(raw))


def test_jpeg_exif_gps_and_comment_are_stripped_and_orientation_applied(app, db, store):
    owner, report = owner_report(app, db)
    src = fx.jpeg_with_exif((40, 20), orientation=6)  # stored sideways; must be rotated into the pixels
    assert Image.open(io.BytesIO(src)).getexif()[fx.EXIF_MAKE] == fx.MARKER  # fixture really carries metadata
    assert upload(owner, report, src).status_code == 201
    raw, img = stored_image(db, store, report)
    assert fx.MARKER.encode() not in raw and b"Exif" not in raw
    assert dict(img.getexif()) == {} and "comment" not in img.info and "exif" not in img.info
    assert img.size == (20, 40)  # orientation baked into pixels, then the tag dropped


def test_png_text_chunks_and_exif_are_stripped(app, db, store):
    owner, report = owner_report(app, db)
    src = fx.png_with_text(alpha=True)
    assert Image.open(io.BytesIO(src)).text["Author"] == fx.MARKER
    assert upload(owner, report, src, "a.png", "image/png").status_code == 201
    raw, img = stored_image(db, store, report)
    assert fx.MARKER.encode() not in raw and img.format == "PNG"
    assert not getattr(img, "text", {}) and dict(img.getexif()) == {}
    assert "A" in img.mode  # transparency preserved


def test_webp_exif_is_stripped(app, db, store):
    owner, report = owner_report(app, db)
    src = fx.webp_with_exif()
    assert Image.open(io.BytesIO(src)).getexif()[fx.EXIF_MAKE] == fx.MARKER
    assert upload(owner, report, src, "a.webp", "image/webp").status_code == 201
    raw, img = stored_image(db, store, report)
    assert fx.MARKER.encode() not in raw and img.format == "WEBP" and dict(img.getexif()) == {}


def test_original_filename_is_never_exposed_or_used_in_key(app, db, store):
    owner, report = owner_report(app, db)
    r = upload(owner, report, fx.jpeg_with_exif(), "../../my secret name.jpg")
    assert r.status_code == 201
    (row,) = attachment_rows(db, report)
    assert "secret" not in row.blob_key and "/" not in row.original_filename and ".." not in row.original_filename
    g = owner.get(f"/api/reports/{report.report_id}/photo")
    assert "secret" not in g.headers["content-disposition"]



# ======================================================================= Task 2.0B: retrieval + delete hardening

def seed_photo(db, store, report, owner_user):
    """Attach a photo directly (bypasses the upload route so terminal-status reports can be tested)."""
    import uuid as _uuid

    from app.core.security import new_id, utcnow
    from app.persistence.models import Attachment
    from app.services.images import process_image

    processed = process_image(fx.jpeg_with_exif())
    key = f"attachments/{_uuid.uuid4()}.{processed.extension}"
    store.put(key, processed.data, processed.content_type)
    db.add(Attachment(
        attachment_id=new_id(), report_id=report.report_id, uploaded_by_user_id=owner_user.user_id,
        attachment_type="REPORT_PHOTO", blob_key=key, original_filename="seed.jpg", content_type=processed.content_type,
        size_bytes=len(processed.data), upload_status="ACTIVE", created_at_utc=utcnow(),
    ))
    db.commit()
    return key


def photo_url(report):
    return f"/api/reports/{report.report_id}/photo"


def anon_client(app):
    from fastapi.testclient import TestClient

    from tests.api_helpers import ORIGIN

    return TestClient(app, headers={"Origin": ORIGIN})


def test_anonymous_get_is_401_and_leaks_nothing(app, db, store):
    owner, report = owner_report(app, db)
    seed_photo(db, store, report, owner.user)
    r = anon_client(app).get(photo_url(report))
    assert r.status_code == 401 and r.headers.get("content-type", "").startswith("application/json")
    assert "attachments/" not in r.text


def test_anonymous_delete_is_401_and_keeps_photo(app, db, store):
    owner, report = owner_report(app, db)
    seed_photo(db, store, report, owner.user)
    assert anon_client(app).delete(photo_url(report)).status_code in (401, 403)
    assert len(list(store.list())) == 1 and [r.upload_status for r in attachment_rows(db, report)] == ["ACTIVE"]


def test_delete_requires_csrf_token(app, db, store):
    owner, report = owner_report(app, db)
    seed_photo(db, store, report, owner.user)
    assert owner.http.delete(photo_url(report)).status_code == 403
    assert len(list(store.list())) == 1


@pytest.mark.parametrize("who", ["owner", "student"])
def test_get_without_a_photo_is_404(app, db, store, who):
    owner, report = owner_report(app, db)
    viewer = owner if who == "owner" else login_api(app, db, name="Other")
    r = viewer.get(photo_url(report))
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_get_photo_of_unknown_report_is_404(app, db, store):
    import uuid

    viewer = login_api(app, db)
    assert viewer.get(f"/api/reports/{uuid.uuid4()}/photo").status_code == 404


def test_moderator_can_get_photo_with_private_headers(app, db, store):
    owner, report = owner_report(app, db)
    seed_photo(db, store, report, owner.user)
    mod = login_api(app, db, "MODERATOR", "Mod")
    g = mod.get(photo_url(report))
    assert g.status_code == 200 and g.headers["cache-control"] == "private, no-store"
    assert g.headers["x-content-type-options"] == "nosniff"
    assert Image.open(io.BytesIO(g.content)).format == "JPEG"


@pytest.mark.parametrize("status,other_student_sees", [
    ("ACTIVE", True), ("RESOLVED", True), ("WITHDRAWN", False), ("CLOSED", False),
])
def test_photo_visibility_follows_report_status(app, db, store, status, other_student_sees):
    owner = login_api(app, db, name="Owner")
    report = make_report(db, owner.user, "FOUND", status=status)
    db.commit()
    seed_photo(db, store, report, owner.user)
    other = login_api(app, db, name="Other")
    mod = login_api(app, db, "MODERATOR", "Mod")
    assert owner.get(photo_url(report)).status_code == 200  # the owner always sees their own report's photo
    assert mod.get(photo_url(report)).status_code == 200
    g = other.get(photo_url(report))
    if other_student_sees:
        assert g.status_code == 200
    else:
        assert g.status_code == 404 and g.json()["error"]["code"] == "NOT_FOUND"  # concealment, not 403


def test_concealed_terminal_report_404_matches_unknown_report_404(app, db, store):
    import uuid

    owner = login_api(app, db, name="Owner")
    report = make_report(db, owner.user, "FOUND", status="CLOSED")
    db.commit()
    seed_photo(db, store, report, owner.user)
    other = login_api(app, db, name="Other")
    hidden = other.get(photo_url(report))
    unknown = other.get(f"/api/reports/{uuid.uuid4()}/photo")
    assert hidden.status_code == unknown.status_code == 404
    assert hidden.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert hidden.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_deactivated_user_cannot_get_photo(app, db, store):
    owner, report = owner_report(app, db)
    seed_photo(db, store, report, owner.user)
    viewer = login_api(app, db, name="Soon Gone")
    assert viewer.get(photo_url(report)).status_code == 200
    db.execute(text("UPDATE users SET is_active = 0 WHERE user_id = :u"), {"u": viewer.user.user_id})
    db.commit()
    r = viewer.get(photo_url(report))
    assert r.status_code == 401 and not r.content.startswith(b"\xff\xd8")


def test_get_response_never_discloses_storage_details(app, db, store):
    owner, report = owner_report(app, db)
    key = seed_photo(db, store, report, owner.user)
    g = owner.get(photo_url(report))
    assert g.status_code == 200
    exposed = " ".join(f"{k}: {v}" for k, v in g.headers.items()).lower()
    assert key.lower() not in exposed and "blob" not in exposed and "sig=" not in exposed and "x-ms" not in exposed
    assert "location" not in g.headers and g.headers["content-disposition"] == 'inline; filename="report-photo.jpg"'
    assert "seed.jpg" not in exposed  # the stored original filename is never echoed back


def test_report_dtos_expose_has_photo_but_no_storage_metadata(app, db, store):
    owner, report = owner_report(app, db)
    other = login_api(app, db, name="Other")
    assert owner.get(f"/api/reports/{report.report_id}").json()["has_photo"] is False
    assert upload(owner, report, fx.jpeg_with_exif()).status_code == 201
    for viewer in (owner, other):
        detail = viewer.get(f"/api/reports/{report.report_id}")
        assert detail.json()["has_photo"] is True
        assert not re.search(r"blob|attachments/|sas|original_filename|attachment_id", detail.text)
        listing = viewer.get("/api/reports?type=FOUND").json()
        row = next(i for i in listing["items"] if i["report_id"] == str(report.report_id))
        assert row["has_photo"] is True
    assert owner.delete(photo_url(report)).status_code == 204
    assert other.get(f"/api/reports/{report.report_id}").json()["has_photo"] is False


def test_get_blob_unavailable_is_503_not_a_leak(app, db, flaky):
    owner, report = owner_report(app, db)
    seed_photo(db, flaky, report, owner.user)

    def broken_get(key):
        raise BlobUnavailableError

    flaky.get = broken_get  # type: ignore[method-assign]
    r = owner.get(photo_url(report))
    assert r.status_code == 503 and r.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "attachments/" not in r.text and "Traceback" not in r.text


# ---------------------------------------------------------------------------------------- DELETE

def test_non_owner_student_cannot_delete_photo_of_active_report(app, db, store):
    owner, report = owner_report(app, db)
    seed_photo(db, store, report, owner.user)
    stranger = login_api(app, db, name="Stranger")
    assert stranger.delete(photo_url(report)).status_code == 403
    assert [r.upload_status for r in attachment_rows(db, report)] == ["ACTIVE"] and len(list(store.list())) == 1


def test_non_owner_student_gets_404_deleting_photo_of_hidden_report(app, db, store):
    owner = login_api(app, db, name="Owner")
    report = make_report(db, owner.user, "FOUND", status="WITHDRAWN")
    db.commit()
    seed_photo(db, store, report, owner.user)
    stranger = login_api(app, db, name="Stranger")
    assert stranger.delete(photo_url(report)).status_code == 404
    assert [r.upload_status for r in attachment_rows(db, report)] == ["ACTIVE"] and len(list(store.list())) == 1


def test_delete_without_a_photo_is_404_and_audits_nothing(app, db, store):
    owner, report = owner_report(app, db)
    assert owner.delete(photo_url(report)).status_code == 404
    assert audit_text(db, "REPORT_PHOTO_DELETED")[0] == []


def test_owner_may_delete_photo_of_terminal_report(app, db, store):
    owner = login_api(app, db, name="Owner")
    report = make_report(db, owner.user, "FOUND", status="CLOSED")
    db.commit()
    seed_photo(db, store, report, owner.user)
    assert owner.delete(photo_url(report)).status_code == 204
    assert [r.upload_status for r in attachment_rows(db, report)] == ["DELETED"] and list(store.list()) == []


def test_moderator_may_delete_photo_of_terminal_report(app, db, store):
    owner = login_api(app, db, name="Owner")
    report = make_report(db, owner.user, "FOUND", status="WITHDRAWN")
    db.commit()
    seed_photo(db, store, report, owner.user)
    mod = login_api(app, db, "MODERATOR", "Mod")
    assert mod.delete(photo_url(report)).status_code == 204
    assert [r.upload_status for r in attachment_rows(db, report)] == ["DELETED"]


def test_delete_audit_event_records_actor_role_and_no_storage_details(app, db, store):
    owner, report = owner_report(app, db)
    key = seed_photo(db, store, report, owner.user)
    mod = login_api(app, db, "MODERATOR", "Mod")
    assert mod.delete(photo_url(report)).status_code == 204
    rows, blob = audit_text(db, "REPORT_PHOTO_DELETED")
    assert len(rows) == 1 and str(mod.user.user_id).lower() in blob.lower() and "MODERATOR" in blob
    assert key not in blob and "seed.jpg" not in blob


def test_delete_when_blob_already_gone_is_success_and_marks_metadata_deleted(app, db, store):
    owner, report = owner_report(app, db)
    key = seed_photo(db, store, report, owner.user)
    store.delete(key)  # blob vanished out-of-band; contract: a Blob 404 on delete counts as success
    assert owner.delete(photo_url(report)).status_code == 204
    (row,) = attachment_rows(db, report)
    assert row.upload_status == "DELETED"


def test_deleted_photo_stays_gone_and_second_delete_is_404(app, db, store):
    owner, report = owner_report(app, db)
    seed_photo(db, store, report, owner.user)
    assert owner.delete(photo_url(report)).status_code == 204
    assert owner.get(photo_url(report)).status_code == 404
    assert owner.delete(photo_url(report)).status_code == 404
    assert len(audit_text(db, "REPORT_PHOTO_DELETED")[0]) == 1


def test_sql_failure_after_blob_delete_is_recoverable_by_retry(app, db, store, monkeypatch):
    """Blob is removed first, so a later SQL failure rolls metadata back to ACTIVE; a retry must still finish cleanly."""
    from fastapi.testclient import TestClient

    from app.services import audit

    owner, report = owner_report(app, db)
    seed_photo(db, store, report, owner.user)
    real = audit.log_event

    def boom(*a, **k):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(audit, "log_event", boom)
    owner.http = TestClient(app, headers=owner.http.headers, cookies=owner.http.cookies, raise_server_exceptions=False)
    assert owner.delete(photo_url(report)).status_code == 500
    assert [r.upload_status for r in attachment_rows(db, report)] == ["ACTIVE"]  # rolled back, never half-deleted
    assert owner.get(photo_url(report)).status_code == 404  # blob is gone, so retrieval fails safely
    monkeypatch.setattr(audit, "log_event", real)
    assert owner.delete(photo_url(report)).status_code == 204  # blob 404 = success, metadata now consistent
    assert [r.upload_status for r in attachment_rows(db, report)] == ["DELETED"]
    assert len(audit_text(db, "REPORT_PHOTO_DELETED")[0]) == 1
