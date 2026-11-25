"""Moderation activity feed API (contract 4.5 / 19). Real SQL Server; reuses the real audit pipeline (no parallel audit system)."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.security import new_id
from app.persistence.models import ActivityLog
from app.services import audit
from tests.api_helpers import login_api, report_body
from tests.helpers import make_user

pytestmark = pytest.mark.sql

URL = "/api/moderation/activity"
ITEM_KEYS = {"activity_id", "event_type", "target_type", "target_id", "actor", "created_at_utc", "outcome", "correlation_id", "metadata"}


@pytest.fixture()
def app(db):
    from app.main import create_app

    return create_app()


def clear_feed(db):
    db.rollback()
    db.execute(text("DELETE FROM activity_logs"))
    db.commit()


def put(db, minutes: int, event_type="REPORT_CREATED", outcome="SUCCESS", target_type="REPORT", actor=None, metadata=None, activity_id=None):
    """Insert one activity row with an exact timestamp (base 2026-06-01T00:00Z + minutes)."""
    row = ActivityLog(
        activity_id=activity_id or new_id(), actor_user_id=actor.user_id if actor else None, event_type=event_type, target_type=target_type,
        target_id=new_id() if target_type != "NONE" else None, created_at_utc=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc) + dt.timedelta(minutes=minutes),
        outcome=outcome, correlation_id=f"corr-{minutes}", metadata_json=json.dumps(metadata) if metadata else None,
    )
    db.add(row)
    db.flush()
    return row


def feed(api, **params):
    return api.get(URL, params=params)


# ---- access ---------------------------------------------------------------------------------------------------
def test_moderator_only_access(app, db):
    assert TestClient(app).get(URL).status_code == 401
    assert login_api(app, db, "STUDENT", "Student").get(URL).status_code == 403
    mod = login_api(app, db, "MODERATOR", "Mod")
    r = feed(mod)
    assert r.status_code == 200 and set(r.json()) == {"items", "page", "page_size", "total"}


def test_student_forbidden_even_with_invalid_params(app, db):
    student = login_api(app, db, "STUDENT", "Student")
    assert feed(student, page=0).status_code == 403 and feed(student, bogus=1).status_code == 403


# ---- empty / pagination / ordering ------------------------------------------------------------------------------
def test_empty_feed(app, db):
    mod = login_api(app, db, "MODERATOR", "Mod")
    clear_feed(db)
    r = feed(mod)
    assert r.status_code == 200 and r.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}


def test_pagination_defaults_clamps_and_page_beyond_last(app, db):
    mod = login_api(app, db, "MODERATOR", "Mod")
    clear_feed(db)
    for i in range(5):
        put(db, i)
    db.commit()
    body = feed(mod).json()
    assert (body["page"], body["page_size"], body["total"], len(body["items"])) == (1, 20, 5, 5)
    assert [len(feed(mod, page=p, page_size=2).json()["items"]) for p in (1, 2, 3)] == [2, 2, 1]
    beyond = feed(mod, page=4, page_size=2)
    assert beyond.status_code == 200 and beyond.json()["items"] == [] and beyond.json()["total"] == 5
    assert feed(mod, page_size=100).status_code == 200
    for bad in ({"page": 0}, {"page_size": 0}, {"page_size": 101}, {"page": "x"}):
        assert feed(mod, **bad).status_code == 422, bad


def test_newest_first_with_stable_tiebreak_across_pages(app, db):
    mod = login_api(app, db, "MODERATOR", "Mod")
    clear_feed(db)
    for minute in (5, 5, 5, 4, 4, 3, 2, 2, 1):  # several identical timestamps force the activity_id tie-break
        put(db, minute)
    db.commit()
    expected = [str(r[0]).lower() for r in db.execute(text("SELECT activity_id FROM activity_logs ORDER BY created_at_utc DESC, activity_id ASC")).all()]
    paged: list[str] = []
    for p in range(1, 6):
        paged += [i["activity_id"] for i in feed(mod, page=p, page_size=2).json()["items"]]
    assert paged == expected and len(set(paged)) == 9  # no row skipped or repeated across pages
    full = feed(mod, page_size=100).json()["items"]
    assert [i["activity_id"] for i in full] == expected
    assert [i["created_at_utc"] for i in full] == sorted((i["created_at_utc"] for i in full), reverse=True)
    assert [i["activity_id"] for i in feed(mod, page_size=100).json()["items"]] == expected  # repeatable


# ---- filtering --------------------------------------------------------------------------------------------------
def test_filters_and_combinations(app, db):
    mod = login_api(app, db, "MODERATOR", "Mod")
    clear_feed(db)
    put(db, 1, "REPORT_CREATED", "SUCCESS", "REPORT")
    put(db, 2, "REPORT_CLOSED", "SUCCESS", "REPORT")
    put(db, 3, "CLAIM_SUBMITTED", "SUCCESS", "CLAIM")
    put(db, 4, "AUTH_LOGIN_FAILED", "FAILURE", "NONE")
    put(db, 5, "MODERATOR_EVIDENCE_ACCESSED", "DENIED", "CLAIM")
    db.commit()
    by_type = feed(mod, event_type="REPORT_CLOSED").json()
    assert by_type["total"] == 1 and by_type["items"][0]["event_type"] == "REPORT_CLOSED"
    assert feed(mod, outcome="FAILURE").json()["total"] == 1
    claim_rows = feed(mod, target_type="CLAIM").json()
    assert claim_rows["total"] == 2 and {i["target_type"] for i in claim_rows["items"]} == {"CLAIM"}
    assert feed(mod, target_type="CLAIM", outcome="DENIED").json()["total"] == 1
    assert feed(mod, event_type="REPORT_CLOSED", outcome="FAILURE").json() == {"items": [], "page": 1, "page_size": 20, "total": 0}
    paged = feed(mod, target_type="CLAIM", page_size=1, page=2).json()
    assert paged["total"] == 2 and len(paged["items"]) == 1  # total reflects the filter, not the page


def test_invalid_filters_and_unknown_params_are_rejected(app, db):
    mod = login_api(app, db, "MODERATOR", "Mod")
    r = feed(mod, event_type="NOT_AN_EVENT")
    assert r.status_code == 422 and "event_type" in r.json()["error"]["field_errors"]
    assert feed(mod, outcome="MAYBE").status_code == 422
    r = feed(mod, actor_user_id="x")
    assert r.status_code == 422 and "actor_user_id" in r.json()["error"]["field_errors"]


# ---- event representation ---------------------------------------------------------------------------------------
def test_event_representation_from_the_real_audit_pipeline(app, db):
    mod = login_api(app, db, "MODERATOR", "Mod Display")
    clear_feed(db)
    actor = make_user(db, "STUDENT", "Actor Student")
    target = new_id()
    audit.log_event(db, event_type="REPORT_UPDATED", outcome="SUCCESS", correlation_id="req-abc", actor_user_id=actor.user_id,
                    target_type="REPORT", target_id=target, metadata={"changed_fields": ["title"], "reason_code": "OWNER_EDIT"})
    audit.log_event(db, event_type="MATCH_JOB_SUCCEEDED", outcome="SYSTEM", correlation_id="job-1")
    db.commit()
    items = feed(mod, page_size=100).json()["items"]
    assert len(items) == 2 and all(set(i) == ITEM_KEYS for i in items)
    upd = next(i for i in items if i["event_type"] == "REPORT_UPDATED")
    assert upd["actor"] == {"user_id": str(actor.user_id), "display_name": "Actor Student"}
    assert upd["target_type"] == "REPORT" and upd["target_id"] == str(target) and upd["outcome"] == "SUCCESS"
    assert upd["correlation_id"] == "req-abc" and upd["created_at_utc"].endswith("Z") and "T" in upd["created_at_utc"]
    assert upd["metadata"] == {"changed_fields": ["title"], "reason_code": "OWNER_EDIT"}
    sysrow = next(i for i in items if i["event_type"] == "MATCH_JOB_SUCCEEDED")
    assert sysrow["actor"] is None and sysrow["target_id"] is None and sysrow["target_type"] == "NONE"
    assert sysrow["outcome"] == "SYSTEM" and sysrow["metadata"] == {}


def test_login_events_are_visible_to_moderator_without_credentials(app, db):
    mod = login_api(app, db, "MODERATOR", "Mod")
    body = feed(mod, event_type="AUTH_LOGIN_SUCCEEDED").json()
    assert body["total"] >= 1 and body["items"][0]["actor"]["display_name"] == "Mod"
    assert "password" not in json.dumps(body).lower() and "csrf" not in json.dumps(body).lower()


# ---- sensitive-data exclusion -----------------------------------------------------------------------------------
def test_metadata_is_allowlisted_even_if_raw_row_contains_secrets(app, db):
    mod = login_api(app, db, "MODERATOR", "Mod")
    clear_feed(db)
    put(db, 1, "CLAIM_SUBMITTED", target_type="CLAIM", metadata={
        "claim_id": "c-1", "claim_statement": "SECRET-STATEMENT", "password": "SECRET-PW", "session_token": "SECRET-TOKEN",
        "blob_key": "attachments/SECRET.jpg", "original_filename": "SECRET.jpg", "email": "x@example.com", "evidence": ["SECRET-EVIDENCE"],
    })
    put(db, 2, "REPORT_CREATED", metadata={"unknown_key": "SECRET-UNKNOWN"})
    put(db, 3, "REPORT_CREATED", metadata=None)
    db.execute(text("INSERT INTO activity_logs (activity_id,event_type,target_type,created_at_utc,outcome,correlation_id,metadata) "
                    "VALUES (NEWID(),'REPORT_CREATED','REPORT','2026-06-01T00:10:00','SUCCESS','c','[1,2,3]')"))  # valid JSON, not an object
    db.commit()
    r = feed(mod, page_size=100)
    assert r.status_code == 200 and "SECRET" not in r.text and "x@example.com" not in r.text
    by_corr = {i["correlation_id"]: i for i in r.json()["items"]}
    assert by_corr["corr-1"]["metadata"] == {"claim_id": "c-1"}
    assert by_corr["corr-2"]["metadata"] == {} and by_corr["corr-3"]["metadata"] == {} and by_corr["c"]["metadata"] == {}


def test_decision_note_only_for_moderator_report_actions(app, db):
    mod = login_api(app, db, "MODERATOR", "Mod")
    clear_feed(db)
    for minute, event in enumerate(("REPORT_CLOSED", "REPORT_REOPENED", "REPORT_MODERATOR_CORRECTED", "MATCH_DISMISSED", "CLAIM_VERIFIED", "CLAIM_REJECTED")):
        put(db, minute, event, metadata={"reason_code": "OTHER", "decision_note": f"note-for-{event}"})
    db.commit()
    got = {i["event_type"]: i["metadata"] for i in feed(mod, page_size=100).json()["items"]}
    for ev in ("REPORT_CLOSED", "REPORT_REOPENED", "REPORT_MODERATOR_CORRECTED"):
        assert got[ev] == {"reason_code": "OTHER", "decision_note": f"note-for-{ev}"}
    for ev in ("MATCH_DISMISSED", "CLAIM_VERIFIED", "CLAIM_REJECTED"):
        assert got[ev] == {"reason_code": "OTHER"}


def test_real_claim_workflow_never_leaks_statement_notes_or_evidence_into_the_feed(app, db):
    finder, claimant = login_api(app, db, name="Finder Person"), login_api(app, db, name="Claimant Person")
    mod = login_api(app, db, "MODERATOR", "Mod")
    found = finder.post("/api/reports", report_body("FOUND")).json()
    stmt = "UNIQUE-SECRET-CLAIM-STATEMENT sewn in the lining"
    claim = claimant.post(f"/api/reports/{found['report_id']}/claims", {"claim_statement": stmt}).json()["claim"]
    mod.get(f"/api/moderation/claims/{claim['claim_id']}")  # moderator detail access is itself audited
    ok = mod.post(f"/api/moderation/claims/{claim['claim_id']}/verify", {"expected_version": claim["version"], "decision_note": "UNIQUE-SECRET-CLAIM-NOTE"})
    assert ok.status_code == 200
    mod.post(f"/api/moderation/claims/{claim['claim_id']}/recover", {"expected_version": ok.json()["claim"]["version"]})
    r = feed(mod, page_size=100)
    types = {i["event_type"] for i in r.json()["items"]}
    assert {"REPORT_CREATED", "CLAIM_SUBMITTED", "CLAIM_VERIFIED", "RECOVERY_COMPLETED"} <= types
    low = r.text.lower()
    for secret in ("unique-secret", "sewn", "password_hash", "csrf", "blob_key", "storage_key", claimant.user.email_normalized, finder.user.email_normalized):
        assert secret.lower() not in low, secret
    submitted = next(i for i in r.json()["items"] if i["event_type"] == "CLAIM_SUBMITTED")
    assert submitted["actor"]["display_name"] == "Claimant Person" and "claim_statement" not in submitted["metadata"]


def test_feed_is_read_only(app, db):
    mod = login_api(app, db, "MODERATOR", "Mod")
    before = db.execute(text("SELECT COUNT(*) FROM activity_logs")).scalar_one()
    db.rollback()
    for _ in range(3):
        feed(mod)
    db.rollback()
    assert db.execute(text("SELECT COUNT(*) FROM activity_logs")).scalar_one() == before
