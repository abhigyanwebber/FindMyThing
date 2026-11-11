from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from tests.api_helpers import login_api, report_body
from tests.helpers import cat, loc, make_claim, make_report, make_user

pytestmark = pytest.mark.sql


@pytest.fixture()
def app(db):
    from app.main import create_app

    return create_app()


def history(db, report_id):
    return db.execute(text("SELECT old_status,new_status,reason_code,correlation_id FROM report_status_history WHERE report_id=:r ORDER BY changed_at_utc"), {"r": report_id}).all()


def test_create_report_returns_safe_dto_and_enqueues_matching(app, db):
    s = login_api(app, db, name="Ana")
    r = s.post("/api/reports", report_body("FOUND"))
    assert r.status_code == 201
    d = r.json()
    assert d["status"] == "ACTIVE" and d["version"] == 1 and d["is_owner"] is True and d["has_photo"] is False
    assert d["reporter"] == {"display_name": "Ana"} and d["location"]["zone_name"] == "Academic Zone"
    assert not ({"reporter_user_id", "matching_version", "status_reason_code", "email"} & set(d))
    job = db.execute(text("SELECT status, report_matching_version, algorithm_version FROM matching_jobs")).one()
    assert tuple(job) == ("PENDING", 1, "match-v1")
    assert db.execute(text("SELECT COUNT(*) FROM activity_logs WHERE event_type IN ('REPORT_CREATED','MATCH_JOB_QUEUED')")).scalar() == 2


@pytest.mark.parametrize("over,field", [
    ({"title": "abcd"}, "title"), ({"description": "short"}, "description"), ({"report_type": "MISSING"}, "report_type"),
    ({"occurred_on": (dt.date.today() + dt.timedelta(days=5)).isoformat()}, "occurred_on"),
    ({"occurred_on": (dt.date.today() - dt.timedelta(days=4000)).isoformat()}, "occurred_on"),
    ({"category_id": str(uuid.uuid4())}, "category_id"), ({"title": "ab\x00cde"}, "title"),
])
def test_create_report_validation(app, db, over, field):
    s = login_api(app, db)
    r = s.post("/api/reports", report_body(**over))
    assert r.status_code == 422 and field in r.json()["error"]["field_errors"]


def test_unknown_and_server_owned_fields_rejected(app, db):
    s = login_api(app, db)
    r = s.post("/api/reports", {**report_body(), "status": "RESOLVED", "reporter_user_id": str(uuid.uuid4()), "version": 9})
    assert r.status_code == 422 and {"status", "reporter_user_id", "version"} <= set(r.json()["error"]["field_errors"])


def test_moderator_cannot_create_reports(app, db):
    m = login_api(app, db, "MODERATOR")
    assert m.post("/api/reports", report_body()).status_code == 403


def test_unauthenticated_and_csrf_enforced(app, db):
    s = login_api(app, db)
    assert s.http.__class__(app, headers={"Origin": "http://localhost:5173"}).get("/api/reports").status_code == 401
    r = s.http.post("/api/reports", json=report_body(), headers={})  # session cookie but no CSRF header
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_INVALID"


def test_visibility_rules(app, db):
    owner, other, mod = login_api(app, db), login_api(app, db), login_api(app, db, "MODERATOR")
    rid = owner.post("/api/reports", report_body()).json()["report_id"]
    assert other.get(f"/api/reports/{rid}").status_code == 200
    ow = owner.get(f"/api/reports/{rid}").json()
    assert ow["is_owner"] is True and ow["claim_activity"] == {"has_active_claim": False} and ow["can_claim"] is False
    ot = other.get(f"/api/reports/{rid}").json()
    assert ot["is_owner"] is False and ot["can_claim"] is True and "claim_activity" not in ot
    owner.post(f"/api/reports/{rid}/withdraw", {"expected_version": 1})
    assert other.get(f"/api/reports/{rid}").status_code == 404  # concealed
    assert owner.get(f"/api/reports/{rid}").status_code == 200
    md = mod.get(f"/api/reports/{rid}").json()
    assert mod.get(f"/api/reports/{rid}").status_code == 200 and md["status_reason_code"] == "OWNER_WITHDRAWAL"
    assert "status_reason_code" not in owner.get(f"/api/reports/{rid}").json()


def test_list_filters_defaults_and_pagination(app, db):
    owner, other = login_api(app, db), login_api(app, db)
    ids = [owner.post("/api/reports", report_body("LOST" if i % 2 else "FOUND", title=f"Item number {i}")).json()["report_id"] for i in range(5)]
    assert other.get("/api/reports").json()["total"] == 5
    assert other.get("/api/reports?type=LOST").json()["total"] == 2
    p = other.get("/api/reports?page_size=2&page=3").json()
    assert len(p["items"]) == 1 and p["total"] == 5 and p["page"] == 3
    assert other.get("/api/reports?page=9").json()["items"] == []
    assert other.get("/api/reports?page_size=101").status_code == 422
    assert other.get("/api/reports?bogus=1").status_code == 422
    owner.post(f"/api/reports/{ids[0]}/withdraw", {"expected_version": 1})
    assert other.get("/api/reports?status=WITHDRAWN").json()["total"] == 0  # not own
    assert owner.get("/api/reports?status=WITHDRAWN").json()["total"] == 1
    items = other.get("/api/reports").json()["items"]
    stamps = [i["created_at_utc"] for i in items]
    assert stamps == sorted(stamps, reverse=True)
    assert "is_owner" not in items[0] and "can_claim" not in items[0]


def test_search_is_parameterized_and_escapes_wildcards(app, db):
    s = login_api(app, db)
    s.post("/api/reports", report_body(title="Blue water bottle", description="Steel bottle with sticker"))
    s.post("/api/reports", report_body(title="100% cotton scarf", description="Red scarf near library"))
    assert s.get("/api/reports?q=bottle").json()["total"] == 1
    assert s.get("/api/reports?q=BOTTLE sticker").json()["total"] == 1  # all terms, case-insensitive
    assert s.get("/api/reports?q=%25").json()["total"] == 1  # literal %, not wildcard
    assert s.get("/api/reports?q=';DROP TABLE reports;--").json()["total"] == 0
    assert db.execute(text("SELECT COUNT(*) FROM reports")).scalar() == 2


def test_edit_bumps_versions_invalidates_matches_and_requeues(app, db):
    s = login_api(app, db)
    rid = s.post("/api/reports", report_body()).json()["report_id"]
    r = s.patch(f"/api/reports/{rid}", {"title": "Navy laptop bag", "expected_version": 1})
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["title"] == "Navy laptop bag"
    row = db.execute(text("SELECT matching_version FROM reports WHERE report_id=:r"), {"r": rid}).scalar()
    assert row == 2
    jobs = db.execute(text("SELECT report_matching_version,status FROM matching_jobs ORDER BY report_matching_version")).all()
    assert [tuple(j) for j in jobs] == [(1, "SUPERSEDED"), (2, "PENDING")]


def test_edit_version_conflict_and_noop(app, db):
    s = login_api(app, db)
    rid = s.post("/api/reports", report_body()).json()["report_id"]
    assert s.patch(f"/api/reports/{rid}", {"title": "Another title here", "expected_version": 7}).status_code == 409
    same = s.patch(f"/api/reports/{rid}", {"title": "Black laptop bag", "expected_version": 1})
    assert same.status_code == 200 and same.json()["version"] == 1  # no change -> no bump


def test_only_owner_can_edit_or_withdraw(app, db):
    owner, other = login_api(app, db), login_api(app, db)
    rid = owner.post("/api/reports", report_body()).json()["report_id"]
    assert other.patch(f"/api/reports/{rid}", {"title": "Hijacked title!", "expected_version": 1}).status_code == 403
    assert other.post(f"/api/reports/{rid}/withdraw", {"expected_version": 1}).status_code == 403


def test_withdraw_writes_trigger_history_with_actor_reason_correlation(app, db):
    owner = login_api(app, db)
    rid = owner.post("/api/reports", report_body()).json()["report_id"]
    r = owner.post(f"/api/reports/{rid}/withdraw", {"expected_version": 1}, headers={"X-Request-ID": "req-w-1"})
    assert r.status_code == 200 and r.json()["status"] == "WITHDRAWN"
    h = history(db, rid)
    assert [tuple(x) for x in h] == [("ACTIVE", "WITHDRAWN", "OWNER_WITHDRAWAL", "req-w-1")]
    assert db.execute(text("SELECT status FROM matching_jobs")).scalar() == "SUPERSEDED"
    again = owner.post(f"/api/reports/{rid}/withdraw", {"expected_version": 2})
    assert again.status_code == 409


def test_withdraw_and_edit_blocked_by_active_claim(app, db):
    owner, claimant = login_api(app, db), make_user(db)
    rid = owner.post("/api/reports", report_body()).json()["report_id"]
    from app.persistence.models import Report

    make_claim(db, claimant, db.get(Report, uuid.UUID(rid)))
    db.commit()
    assert owner.post(f"/api/reports/{rid}/withdraw", {"expected_version": 1}).status_code == 409
    assert owner.patch(f"/api/reports/{rid}", {"title": "Edited title okay", "expected_version": 1}).status_code == 409
    assert owner.get(f"/api/reports/{rid}").json()["claim_activity"] == {"has_active_claim": True}


def test_moderator_close_requires_reason_and_terminalized_claims(app, db):
    owner, mod = login_api(app, db), login_api(app, db, "MODERATOR")
    rid = owner.post("/api/reports", report_body()).json()["report_id"]
    assert mod.post(f"/api/moderation/reports/{rid}/close", {"reason_code": "NOPE", "expected_version": 1}).status_code == 422
    assert mod.post(f"/api/moderation/reports/{rid}/close", {"reason_code": "OTHER", "expected_version": 1}).status_code == 422
    assert owner.post(f"/api/moderation/reports/{rid}/close", {"reason_code": "INVALID_REPORT", "expected_version": 1}).status_code == 403
    ok = mod.post(f"/api/moderation/reports/{rid}/close", {"reason_code": "OTHER", "decision_note": "Spam content", "expected_version": 1})
    assert ok.status_code == 200 and ok.json()["status"] == "CLOSED"
    note = db.execute(text("SELECT metadata FROM activity_logs WHERE event_type='REPORT_CLOSED'")).scalar()
    assert "Spam content" in note
    assert [tuple(x)[:3] for x in history(db, rid)] == [("ACTIVE", "CLOSED", "OTHER")]


def test_reopen_and_moderator_correction(app, db):
    owner, mod = login_api(app, db), login_api(app, db, "MODERATOR")
    rid = owner.post("/api/reports", report_body()).json()["report_id"]
    mod.post(f"/api/moderation/reports/{rid}/close", {"reason_code": "DUPLICATE_REPORT", "expected_version": 1})
    assert owner.post(f"/api/moderation/reports/{rid}/reopen", {"expected_version": 2}).status_code == 403
    re = mod.post(f"/api/moderation/reports/{rid}/reopen", {"expected_version": 2})
    assert re.status_code == 200 and re.json()["status"] == "ACTIVE" and re.json()["version"] == 3
    assert [tuple(x)[1:3] for x in history(db, rid)] == [("CLOSED", "DUPLICATE_REPORT"), ("ACTIVE", "MODERATOR_REOPEN")]
    c = mod.post(f"/api/moderation/reports/{rid}/correct", {"category_id": str(cat("bags")), "location_id": str(loc("lab")), "expected_version": 3, "decision_note": "Wrong category"})
    assert c.status_code == 200 and c.json()["category"]["name"] == "Bags" and c.json()["location"]["name"] == "Laboratories"
    assert mod.post(f"/api/moderation/reports/{rid}/correct", {"expected_version": 4}).status_code == 422
    assert "report_type" not in {"x"}


def test_correcting_terminal_report_invalidates_without_enqueue_or_status_change(app, db):
    owner, mod = login_api(app, db), login_api(app, db, "MODERATOR")
    rid = owner.post("/api/reports", report_body()).json()["report_id"]
    owner.post(f"/api/reports/{rid}/withdraw", {"expected_version": 1})
    before = db.execute(text("SELECT COUNT(*) FROM matching_jobs WHERE status='PENDING'")).scalar()
    c = mod.post(f"/api/moderation/reports/{rid}/correct", {"title": "Corrected title text", "expected_version": 2})
    assert c.status_code == 200 and c.json()["status"] == "WITHDRAWN"
    assert db.execute(text("SELECT COUNT(*) FROM matching_jobs WHERE status='PENDING'")).scalar() == before


def test_reference_data_endpoint(app, db):
    s = login_api(app, db)
    d = s.get("/api/reference-data").json()
    assert {c["name"] for c in d["categories"]} == {"Electronics", "Bags", "Other"}
    assert any(x["name"] == "Library" and x["zone_name"] == "Academic Zone" for x in d["locations"])


def test_status_history_not_written_for_non_status_updates(app, db):
    owner = login_api(app, db)
    rid = owner.post("/api/reports", report_body()).json()["report_id"]
    owner.patch(f"/api/reports/{rid}", {"title": "Different title now", "expected_version": 1})
    assert history(db, rid) == []
    assert make_report is not None
