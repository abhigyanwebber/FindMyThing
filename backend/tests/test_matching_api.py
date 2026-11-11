from __future__ import annotations

import datetime as dt
import threading
import uuid

import pytest
from sqlalchemy import text

from tests.api_helpers import login_api, report_body
from tests.helpers import cat, loc

pytestmark = pytest.mark.sql


@pytest.fixture()
def app(db):
    from app.main import create_app

    return create_app()


def run():
    from app.services.matching_worker import run_due_jobs

    return run_due_jobs()


def rows(db, sql, **p):
    db.rollback()  # drop snapshot so we see other connections' commits
    return db.execute(text(sql), p).all()


def make_pair(app, db, *, lost_over=None, found_over=None):
    a, b = login_api(app, db, name="Lost Owner"), login_api(app, db, name="Finder")
    lost = a.post("/api/reports", report_body("LOST", **(lost_over or {}))).json()
    found = b.post("/api/reports", report_body("FOUND", **(found_over or {}))).json()
    return a, b, lost, found


def test_identical_pair_becomes_potential_match_visible_to_both_owners(app, db):
    a, b, lost, found = make_pair(app, db)
    assert run() == 2
    m = a.get(f"/api/reports/{lost['report_id']}/matches").json()
    assert m["total"] == 1
    item = m["items"][0]
    assert item["score"] == 100.0 and item["match_status"] == "POTENTIAL" and item["algorithm_version"] == "match-v1"
    assert item["factors"] == {"category": 100.0, "location": 100.0, "date": 100.0, "keywords": 100.0}
    cp = item["counterpart_report"]
    assert cp["report_id"] == found["report_id"] and cp["report_type"] == "FOUND"
    assert not ({"reporter", "reporter_user_id", "email", "description"} & set(cp))  # no private data
    assert set(item) == {"match_id", "counterpart_report", "score", "factors", "explanation", "calculated_at_utc", "algorithm_version", "match_status"}
    assert b.get(f"/api/reports/{found['report_id']}/matches").json()["items"][0]["counterpart_report"]["report_id"] == lost["report_id"]
    # one canonical row per pair even though both reports were processed
    assert rows(db, "SELECT COUNT(*) FROM matches")[0][0] == 1
    assert rows(db, "SELECT COUNT(*) FROM matching_jobs WHERE status='SUCCEEDED'")[0][0] == 2


def test_below_threshold_is_suppressed_hidden_from_students_visible_to_moderators(app, db):
    mod = login_api(app, db, "MODERATOR")
    a, _b, lost, _f = make_pair(app, db, found_over={"category_id": str(cat("bags")), "location_id": str(loc("hostel")),
                                                      "title": "Umbrella", "description": "Folding umbrella, green"})
    run()
    assert a.get(f"/api/reports/{lost['report_id']}/matches").json()["total"] == 0
    mm = mod.get(f"/api/reports/{lost['report_id']}/matches").json()
    assert mm["total"] == 1 and mm["items"][0]["match_status"] == "SUPPRESSED" and mm["items"][0]["score"] < 50


def test_candidates_outside_30_day_window_are_excluded(app, db):
    mod = login_api(app, db, "MODERATOR")
    far = (dt.date.today() - dt.timedelta(days=31)).isoformat()
    _a, _b, lost, _f = make_pair(app, db, found_over={"occurred_on": far})
    run()
    assert mod.get(f"/api/reports/{lost['report_id']}/matches").json()["total"] == 0


def test_same_type_never_matched_and_nonowner_cannot_list(app, db):
    a, b = login_api(app, db), login_api(app, db)
    r1 = a.post("/api/reports", report_body("LOST")).json()
    b.post("/api/reports", report_body("LOST"))
    run()
    assert rows(db, "SELECT COUNT(*) FROM matches")[0][0] == 0
    assert b.get(f"/api/reports/{r1['report_id']}/matches").status_code == 403
    assert login_api(app, db, "MODERATOR").get(f"/api/reports/{r1['report_id']}/matches").status_code == 200


def test_ranking_is_deterministic_score_then_gap(app, db):
    a = login_api(app, db)
    lost = a.post("/api/reports", report_body("LOST")).json()
    f = login_api(app, db)
    near = f.post("/api/reports", report_body("FOUND", title="Black laptop bag", occurred_on=dt.date.today().isoformat())).json()
    far = f.post("/api/reports", report_body("FOUND", title="Black laptop bag", occurred_on=(dt.date.today() - dt.timedelta(days=10)).isoformat())).json()
    same_loc_other = f.post("/api/reports", report_body("FOUND", location_id=loc("lab"), title="Black laptop bag")).json()
    run()
    items = a.get(f"/api/reports/{lost['report_id']}/matches").json()["items"]
    order = [i["counterpart_report"]["report_id"] for i in items]
    # 10-day gap scores 91.67 > same-zone location (90.00), so `far` outranks `same_loc_other`.
    assert order == [near["report_id"], far["report_id"], same_loc_other["report_id"]]
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True)
    assert a.get(f"/api/reports/{lost['report_id']}/matches?page_size=2&page=2").json()["items"][0]["counterpart_report"]["report_id"] == same_loc_other["report_id"]


def test_edit_invalidates_then_rescoring_updates_same_row(app, db):
    a, _b, lost, _f = make_pair(app, db)
    run()
    mid = rows(db, "SELECT match_id, found_report_matching_version FROM matches")[0]
    a.patch(f"/api/reports/{lost['report_id']}", {"title": "Completely different words", "description": "Nothing in common with before", "expected_version": 1})
    st = rows(db, "SELECT match_status, invalidation_reason FROM matches")[0]
    assert tuple(st) == ("INVALIDATED", "REPORT_EDITED")
    assert a.get(f"/api/reports/{lost['report_id']}/matches").json()["total"] == 0  # old result never shown as current
    run()
    after = rows(db, "SELECT match_id, match_status, lost_report_matching_version, invalidated_at_utc, score FROM matches")
    assert len(after) == 1 and str(after[0][0]) == str(mid[0])  # same row reused
    assert after[0][2] == 2 and after[0][3] is None and after[0][1] == "POTENTIAL"
    assert float(after[0][4]) < 100
    ev = rows(db, "SELECT metadata FROM activity_logs WHERE event_type='MATCH_JOB_SUCCEEDED' AND target_type='MATCH'")
    assert ev and "old_score" in ev[0][0]  # prior calculation preserved in audit trail


def test_withdraw_invalidates_matches_and_hides_them(app, db):
    mod = login_api(app, db, "MODERATOR")
    a, b, lost, found = make_pair(app, db)
    run()
    b.post(f"/api/reports/{found['report_id']}/withdraw", {"expected_version": 1})
    assert a.get(f"/api/reports/{lost['report_id']}/matches").json()["total"] == 0
    assert b.get(f"/api/reports/{found['report_id']}/matches").json()["total"] == 0  # terminal -> empty for students
    mm = mod.get(f"/api/reports/{found['report_id']}/matches").json()
    assert mm["items"][0]["match_status"] == "INVALIDATED"


def test_dismiss_rules_and_persistence_and_reset(app, db):
    mod = login_api(app, db, "MODERATOR")
    a, _b, lost, _found = make_pair(app, db)
    run()
    mid = a.get(f"/api/reports/{lost['report_id']}/matches").json()["items"][0]["match_id"]
    assert a.post(f"/api/moderation/matches/{mid}/dismiss", {"reason_code": "INVALID_MATCH"}).status_code == 403
    assert mod.post(f"/api/moderation/matches/{mid}/dismiss", {"reason_code": "BOGUS"}).status_code == 422
    assert mod.post(f"/api/moderation/matches/{mid}/dismiss", {"reason_code": "OTHER"}).status_code == 422
    ok = mod.post(f"/api/moderation/matches/{mid}/dismiss", {"reason_code": "OTHER", "decision_note": "Different brand"})
    assert ok.status_code == 200 and ok.json()["match_status"] == "DISMISSED"
    assert mod.post(f"/api/moderation/matches/{mid}/dismiss", {"reason_code": "INVALID_MATCH"}).status_code == 409
    assert mod.post(f"/api/moderation/matches/{uuid.uuid4()}/dismiss", {"reason_code": "INVALID_MATCH"}).status_code == 404
    assert a.get(f"/api/reports/{lost['report_id']}/matches").json()["total"] == 0
    # explicit recalculation with unchanged versions: dismissal persists
    assert a.post(f"/api/reports/{lost['report_id']}/matches/recalculate", {}).status_code == 202
    run()
    assert rows(db, "SELECT match_status FROM matches")[0][0] == "DISMISSED"
    # materially changed report: dismissal resets to POTENTIAL
    a.patch(f"/api/reports/{lost['report_id']}", {"title": "Black laptop bag v2", "expected_version": 1})
    run()
    assert rows(db, "SELECT match_status FROM matches")[0][0] == "POTENTIAL"
    assert "Different brand" in rows(db, "SELECT metadata FROM activity_logs WHERE event_type='MATCH_DISMISSED'")[0][0]


def test_recalculate_semantics_and_rate_limit(app, db):
    a = login_api(app, db)
    rid = a.post("/api/reports", report_body("LOST")).json()["report_id"]
    first = a.post(f"/api/reports/{rid}/matches/recalculate", {})
    assert first.status_code == 200 and first.json()["status"] == "PENDING"  # creation job still pending
    run()
    again = a.post(f"/api/reports/{rid}/matches/recalculate", {})
    assert again.status_code == 202 and again.json()["status"] == "PENDING"
    assert again.json()["job_id"] == first.json()["job_id"]  # same idempotency-key row, no duplicate
    assert rows(db, "SELECT COUNT(*) FROM matching_jobs")[0][0] == 1
    assert a.post(f"/api/reports/{rid}/matches/recalculate", {"x": 1}).status_code == 422
    other = login_api(app, db)
    assert other.post(f"/api/reports/{rid}/matches/recalculate", {}).status_code == 403
    for _ in range(2):
        assert a.post(f"/api/reports/{rid}/matches/recalculate", {}).status_code in (200, 202)
    r = a.post(f"/api/reports/{rid}/matches/recalculate", {})  # 5th allowed
    r6 = a.post(f"/api/reports/{rid}/matches/recalculate", {})
    assert r.status_code in (200, 202) and r6.status_code == 429 and "Retry-After" in r6.headers


def test_recalculate_requires_active_report(app, db):
    a = login_api(app, db)
    rid = a.post("/api/reports", report_body("LOST")).json()["report_id"]
    a.post(f"/api/reports/{rid}/withdraw", {"expected_version": 1})
    assert a.post(f"/api/reports/{rid}/matches/recalculate", {}).status_code == 409


def test_job_for_stale_version_is_superseded_and_current_version_processed(app, db):
    a, _b, lost, _f = make_pair(app, db)
    a.patch(f"/api/reports/{lost['report_id']}", {"title": "Navy laptop bag", "expected_version": 1})
    # force the stale job back to PENDING to simulate a worker that picked it up late
    db.execute(text("UPDATE matching_jobs SET status='PENDING', next_attempt_at_utc=SYSUTCDATETIME() WHERE report_matching_version=1"))
    db.commit()
    run()
    statuses = {tuple(r) for r in rows(db, "SELECT report_matching_version, status FROM matching_jobs WHERE report_id=:r", r=lost["report_id"])}
    assert (1, "SUPERSEDED") in statuses and (2, "SUCCEEDED") in statuses


def test_failure_backoff_then_dead_after_eight_attempts(app, db, monkeypatch):
    from app.services import matching_worker as w

    a = login_api(app, db)
    a.post("/api/reports", report_body("LOST"))
    monkeypatch.setattr(w.m, "score_pair", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom secret detail")))
    b = login_api(app, db)
    b.post("/api/reports", report_body("FOUND"))  # gives the LOST job a candidate to score -> failure
    job_ids = [r[0] for r in rows(db, "SELECT job_id FROM matching_jobs")]
    for attempt in range(1, 9):
        db.execute(text("UPDATE matching_jobs SET next_attempt_at_utc=SYSUTCDATETIME() WHERE status='PENDING'"))
        db.commit()
        w.run_due_jobs()
        state = rows(db, "SELECT status, attempt_count, last_error_code, next_attempt_at_utc FROM matching_jobs WHERE attempt_count=:n", n=attempt)
        assert state, f"no job at attempt {attempt}"
    dead = rows(db, "SELECT status, attempt_count, last_error_code FROM matching_jobs WHERE status='DEAD'")
    assert dead and dead[0][1] == 8 and dead[0][2] == "ERR_RuntimeError"
    assert "boom" not in str(rows(db, "SELECT metadata FROM activity_logs WHERE event_type='MATCH_JOB_FAILED'"))  # sanitized
    assert job_ids


def test_retry_delay_formula():
    from app.services.matching_worker import retry_delay_seconds as d

    jid = uuid.UUID(int=0)
    assert d(jid, 1) == 2 and d(jid, 3) == 8
    assert d(jid, 20) == 3600  # capped at one hour
    hi = d(uuid.UUID(int=1500), 4)
    assert 16 <= hi <= 16 * 1.15 + 1e-9 and d(uuid.UUID(int=1500), 4) == hi  # deterministic jitter


def test_lease_prevents_double_processing_and_expired_lease_is_reclaimed(app, db):
    from app.persistence.database import get_sessionmaker
    from app.services.matching_worker import lease_next_job

    login_api(app, db).post("/api/reports", report_body("LOST"))
    results: list = []
    barrier = threading.Barrier(4)

    def attempt():
        barrier.wait()
        with get_sessionmaker()() as s:
            results.append(lease_next_job(s))

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(1 for r in results if r is not None) == 1  # exactly one worker won the lease
    assert rows(db, "SELECT status FROM matching_jobs")[0][0] == "PROCESSING"
    db.execute(text("UPDATE matching_jobs SET lease_expires_at_utc=DATEADD(minute,-1,SYSUTCDATETIME())"))
    db.commit()
    with get_sessionmaker()() as s:
        assert lease_next_job(s) is not None  # crashed worker's job is picked up again


def test_job_rows_survive_without_a_worker_and_are_processed_later(app, db):
    login_api(app, db).post("/api/reports", report_body("LOST"))
    assert rows(db, "SELECT status FROM matching_jobs")[0][0] == "PENDING"  # durable outbox, no worker running
    run()
    assert rows(db, "SELECT status FROM matching_jobs")[0][0] == "SUCCEEDED"
