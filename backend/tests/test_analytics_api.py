"""Moderator analytics summary API (contract 4.5 / 22). Real SQL Server; rows are inserted at ORM level so cohort dates,
recovery instants and statuses are exact, plus one end-to-end test through the real report -> claim -> recovery flow."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.security import new_id
from app.persistence.models import ClaimStatusHistory, Recovery
from tests.api_helpers import login_api, report_body
from tests.helpers import cat, loc, make_claim, make_report, make_user

pytestmark = pytest.mark.sql

URL = "/api/moderation/analytics/summary"
NOW = dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.timezone.utc)  # campus tz in tests is Asia/Kolkata (UTC+05:30, no DST)
CONTRACT_KEYS = {
    "period", "lost_reports", "found_reports", "active_reports", "claims", "recoveries", "recovery_rate_pct",
    "recovery_rate_non_withdrawn_pct", "by_category", "by_location", "monthly", "average_recovery_days", "median_recovery_days",
}
ADDITIVE_KEYS = {"report_status_counts", "recovery_rate_basis"}


def utc(y, m, d, h=0, mi=0, s=0) -> dt.datetime:
    return dt.datetime(y, m, d, h, mi, s, tzinfo=dt.timezone.utc)


@pytest.fixture()
def app(db):
    from app.main import create_app

    return create_app()


@pytest.fixture()
def fixed_now(monkeypatch):
    monkeypatch.setattr("app.services.analytics.utcnow", lambda: NOW)
    return NOW


class World:
    def __init__(self, db):
        self.db = db
        self.owner = make_user(db, "STUDENT", "Reporter")
        self.staff = make_user(db, "MODERATOR", "Handler")

    def report(self, rtype="FOUND", created=utc(2026, 6, 1, 6), status="ACTIVE", category="electronics", location="library"):
        r = make_report(self.db, self.owner, rtype, category=category, location=location, status=status)
        r.created_at_utc = created
        self.db.flush()
        return r

    def claim(self, found, created=utc(2026, 6, 1, 7), status="PENDING"):
        c = make_claim(self.db, make_user(self.db, "STUDENT", "Claimant"), found, status=status)
        c.created_at_utc = created
        self.db.flush()
        return c

    def recovery(self, found, completed, status="COMPLETED", verified_at=None):
        claim = self.claim(found, status="RECOVERED" if status == "COMPLETED" else "VERIFIED")
        if verified_at:
            claim.reviewed_at_utc = verified_at
        rec = Recovery(
            recovery_id=new_id(), claim_id=claim.claim_id, found_report_id=found.report_id, lost_report_id=None, status=status,
            completed_by_moderator_id=self.staff.user_id, completed_at_utc=completed, found_prior_status="ACTIVE",
            found_prior_version=1, found_post_version=2,
        )
        if status == "VOIDED":
            rec.voided_by_moderator_id, rec.voided_at_utc, rec.void_reason_code = self.staff.user_id, completed + dt.timedelta(hours=1), "OTHER"
        self.db.add(rec)
        self.db.flush()
        return rec

    def transition(self, claim, new_status, at):
        self.db.add(ClaimStatusHistory(
            history_id=new_id(), claim_id=claim.claim_id, old_status="PENDING", new_status=new_status, changed_by_user_id=None,
            changed_at_utc=at, reason_code="TEST", note=None, correlation_id="test",
        ))
        self.db.flush()


def moderator(app, db):
    return login_api(app, db, "MODERATOR", "Analyst")


def get(api, **params):
    r = api.get(URL, params=params)
    return r


# ---- access ---------------------------------------------------------------------------------------------------
def test_moderator_only_access(app, db, fixed_now):
    anon = TestClient(app).get(URL)
    assert anon.status_code == 401 and anon.json()["error"]["code"] == "UNAUTHENTICATED"
    assert login_api(app, db, "STUDENT", "Student").get(URL).status_code == 403
    ok = get(moderator(app, db))
    assert ok.status_code == 200 and CONTRACT_KEYS <= set(ok.json())


def test_student_forbidden_even_with_invalid_params(app, db, fixed_now):
    student = login_api(app, db, "STUDENT", "Student")
    assert student.get(URL, params={"from": "garbage"}).status_code == 403
    assert student.get(URL, params={"bogus": "1"}).status_code == 403


# ---- empty database / defaults --------------------------------------------------------------------------------
def test_empty_database_returns_zeros_and_nulls_not_zero_rates(app, db, fixed_now):
    body = get(moderator(app, db)).json()
    assert body["period"] == {"from": "2026-03-18", "to": "2026-06-15", "as_of_utc": "2026-06-15T12:00:00.000Z"}  # 90 days inclusive
    assert (body["lost_reports"], body["found_reports"], body["active_reports"], body["recoveries"]) == (0, 0, 0, 0)
    assert body["claims"] == {"submitted": 0, "verified": 0, "rejected": 0, "cancelled": 0}
    assert body["recovery_rate_pct"] is None and body["recovery_rate_non_withdrawn_pct"] is None  # null, never 0
    assert body["average_recovery_days"] is None and body["median_recovery_days"] is None
    assert body["by_category"] == [] and body["by_location"] == []
    assert [m["month"] for m in body["monthly"]] == ["2026-03", "2026-04", "2026-05", "2026-06"]
    assert all((m["lost"], m["found"], m["recoveries"]) == (0, 0, 0) for m in body["monthly"])
    assert body["recovery_rate_basis"] == {"recovered_found_reports": 0, "found_reports": 0, "found_reports_non_withdrawn": 0}


def test_response_shape_is_contract_plus_documented_additive_fields(app, db, fixed_now):
    assert set(get(moderator(app, db)).json()) == CONTRACT_KEYS | ADDITIVE_KEYS


# ---- counts by type/status -------------------------------------------------------------------------------------
def test_counts_by_type_and_status(app, db, fixed_now):
    w = World(db)
    w.report("LOST")
    w.report("LOST", status="RESOLVED")
    w.report("LOST", status="WITHDRAWN")
    w.report("FOUND")
    w.report("FOUND", status="CLOSED")
    db.commit()
    body = get(moderator(app, db)).json()
    assert body["lost_reports"] == 3 and body["found_reports"] == 2 and body["active_reports"] == 2
    assert body["report_status_counts"] == {
        "lost": {"ACTIVE": 1, "RESOLVED": 1, "WITHDRAWN": 1, "CLOSED": 0},
        "found": {"ACTIVE": 1, "RESOLVED": 0, "WITHDRAWN": 0, "CLOSED": 1},
    }


# ---- recovery rate ---------------------------------------------------------------------------------------------
def test_recovery_rate_numerator_denominator_withdrawn_and_closed(app, db, fixed_now):
    w = World(db)
    recovered = w.report("FOUND", status="RESOLVED")
    w.recovery(recovered, utc(2026, 6, 5))
    w.report("FOUND")  # ACTIVE
    w.report("FOUND", status="WITHDRAWN")
    w.report("FOUND", status="CLOSED")
    w.report("LOST")  # LOST reports never enter the FOUND cohort
    w.report("LOST", status="RESOLVED")
    db.commit()
    body = get(moderator(app, db)).json()
    assert body["found_reports"] == 4
    assert body["recovery_rate_pct"] == 25.0  # 1 / 4: WITHDRAWN and CLOSED stay in the denominator
    assert body["recovery_rate_non_withdrawn_pct"] == 33.3  # 1 / 3: only WITHDRAWN leaves; CLOSED stays
    assert body["recovery_rate_basis"] == {"recovered_found_reports": 1, "found_reports": 4, "found_reports_non_withdrawn": 3}
    assert body["report_status_counts"]["found"] == {"ACTIVE": 1, "RESOLVED": 1, "WITHDRAWN": 1, "CLOSED": 1}


def test_voided_recovery_is_not_counted(app, db, fixed_now):
    w = World(db)
    w.recovery(w.report("FOUND"), utc(2026, 6, 5), status="VOIDED")
    db.commit()
    body = get(moderator(app, db)).json()
    assert body["recovery_rate_pct"] == 0.0 and body["recovery_rate_non_withdrawn_pct"] == 0.0  # denominator exists: 0.0, not null
    assert body["recoveries"] == 0 and body["average_recovery_days"] is None and body["median_recovery_days"] is None
    assert body["by_category"][0]["recoveries"] == 0


def test_recovery_completed_after_as_of_is_excluded(app, db, fixed_now):
    w = World(db)
    w.recovery(w.report("FOUND"), utc(2026, 6, 16, 3))  # after the snapshot instant
    db.commit()
    body = get(moderator(app, db), to="2026-06-20").json()
    assert body["recovery_rate_basis"]["recovered_found_reports"] == 0 and body["recovery_rate_pct"] == 0.0
    assert body["recoveries"] == 0 and body["average_recovery_days"] is None


def test_recovery_in_period_of_report_created_before_cohort_is_not_in_the_rate(app, db, fixed_now):
    w = World(db)
    old = w.report("FOUND", created=utc(2026, 1, 10), status="RESOLVED")
    w.recovery(old, utc(2026, 6, 5))
    db.commit()
    body = get(moderator(app, db)).json()
    assert body["recoveries"] == 1  # recovery-event view: completed in the period
    assert body["found_reports"] == 0 and body["recovery_rate_pct"] is None  # cohort view: report created outside the period
    assert body["average_recovery_days"] is None and body["median_recovery_days"] is None
    assert body["by_category"] == [] and sum(m["recoveries"] for m in body["monthly"]) == 0


# ---- cohort boundaries ----------------------------------------------------------------------------------------
def test_cohort_boundaries_use_campus_local_dates_inclusive(app, db, fixed_now):
    w = World(db)
    w.report("FOUND", created=utc(2026, 6, 1, 18, 29, 59))  # 23:59:59 local on 06-01  -> outside
    w.report("FOUND", created=utc(2026, 6, 1, 18, 30, 0))  # 00:00:00 local on 06-02  -> inside
    w.report("FOUND", created=utc(2026, 6, 2, 18, 29, 59))  # 23:59:59 local on 06-02  -> inside
    w.report("FOUND", created=utc(2026, 6, 2, 18, 30, 0))  # 00:00:00 local on 06-03  -> outside
    db.commit()
    body = get(moderator(app, db), **{"from": "2026-06-02", "to": "2026-06-02"}).json()
    assert body["period"]["from"] == body["period"]["to"] == "2026-06-02"
    assert body["found_reports"] == 2


def test_default_window_and_single_sided_params(app, db, fixed_now):
    api = moderator(app, db)
    assert get(api, to="2026-06-02").json()["period"] == {"from": "2026-03-05", "to": "2026-06-02", "as_of_utc": "2026-06-15T12:00:00.000Z"}
    assert get(api, **{"from": "2026-06-01"}).json()["period"]["to"] == "2026-06-15"


def test_period_validation(app, db, fixed_now):
    api = moderator(app, db)
    assert get(api, **{"from": "2026-06-10", "to": "2026-06-09"}).status_code == 422
    assert get(api, **{"from": "2025-06-14", "to": "2026-06-15"}).status_code == 422  # 367 days inclusive
    assert get(api, **{"from": "2025-06-15", "to": "2026-06-15"}).status_code == 200  # 366 days inclusive
    assert get(api, **{"from": "not-a-date"}).status_code == 422
    r = get(api, bogus="1")
    assert r.status_code == 422 and "bogus" in r.json()["error"]["field_errors"]


# ---- time to recovery -----------------------------------------------------------------------------------------
CREATED = utc(2026, 5, 1)


@pytest.mark.parametrize(
    ("days", "avg", "median"),
    [([1, 2, 6], 3.0, 2.0), ([1, 2], 1.5, 1.5), ([1.25], 1.3, 1.3), ([0.04], 0.0, 0.0)],
)
def test_average_and_median_days_from_report_creation_to_completed_recovery(app, db, fixed_now, days, avg, median):
    w = World(db)
    for d in days:
        w.recovery(w.report("FOUND", created=CREATED, status="RESOLVED"), CREATED + dt.timedelta(days=d))
    db.commit()
    body = get(moderator(app, db)).json()
    assert body["average_recovery_days"] == avg and body["median_recovery_days"] == median  # one decimal, half-up
    assert body["recovery_rate_pct"] == 100.0


def test_time_to_recovery_uses_physical_recovery_not_claim_verification(app, db, fixed_now):
    w = World(db)
    rep = w.report("FOUND", created=CREATED, status="RESOLVED")
    w.recovery(rep, CREATED + dt.timedelta(days=4), verified_at=CREATED + dt.timedelta(hours=1))
    db.commit()
    body = get(moderator(app, db)).json()
    assert body["average_recovery_days"] == 4.0 and body["median_recovery_days"] == 4.0


def test_time_to_recovery_ignores_unrecovered_and_voided(app, db, fixed_now):
    w = World(db)
    w.recovery(w.report("FOUND", created=CREATED, status="RESOLVED"), CREATED + dt.timedelta(days=2))
    w.recovery(w.report("FOUND", created=CREATED), CREATED + dt.timedelta(days=30), status="VOIDED")
    w.report("FOUND", created=CREATED)
    db.commit()
    body = get(moderator(app, db)).json()
    assert body["average_recovery_days"] == 2.0 and body["median_recovery_days"] == 2.0
    assert body["recovery_rate_pct"] == 33.3


# ---- claim metrics --------------------------------------------------------------------------------------------
def test_claim_counts_are_period_events(app, db, fixed_now):
    w = World(db)
    found = w.report("FOUND")
    c1 = w.claim(found, created=utc(2026, 6, 2))
    c2 = w.claim(found, created=utc(2026, 6, 3))
    c3 = w.claim(found, created=utc(2026, 3, 1))  # before the default window
    w.transition(c1, "VERIFIED", utc(2026, 6, 2, 1))
    w.transition(c1, "VERIFIED", utc(2026, 6, 3, 1))  # re-verification after a revoke: two transition EVENTS
    w.transition(c2, "REJECTED", utc(2026, 6, 4))
    w.transition(c3, "CANCELLED", utc(2026, 6, 5))  # event in period even though the claim was created earlier
    w.transition(c3, "VERIFIED", utc(2026, 3, 1, 1))  # before the window
    w.transition(c2, "CANCELLED", utc(2026, 6, 16))  # after the window end
    w.transition(c2, "PENDING", utc(2026, 6, 5))  # not a counted transition target
    db.commit()
    assert get(moderator(app, db)).json()["claims"] == {"submitted": 2, "verified": 2, "rejected": 1, "cancelled": 1}


# ---- category / location distributions -------------------------------------------------------------------------
def test_category_and_location_distributions_sorted_with_cohort_recoveries(app, db, fixed_now):
    w = World(db)
    w.recovery(w.report("FOUND", category="electronics", location="library", status="RESOLVED"), utc(2026, 6, 5))
    w.report("FOUND", category="electronics", location="library")
    w.report("LOST", category="electronics", location="library")
    w.report("FOUND", category="bags", location="hostel")
    w.report("LOST", category="other", location="lab")
    w.report("LOST", category="bags", location="hostel", created=utc(2026, 1, 1))  # outside the cohort
    db.commit()
    body = get(moderator(app, db)).json()
    assert body["by_category"] == [
        {"category_id": str(cat("bags")), "name": "Bags", "lost": 0, "found": 1, "recoveries": 0},
        {"category_id": str(cat("electronics")), "name": "Electronics", "lost": 1, "found": 2, "recoveries": 1},
        {"category_id": str(cat("other")), "name": "Other", "lost": 1, "found": 0, "recoveries": 0},
    ]
    assert body["by_location"] == [
        {"location_id": str(loc("hostel")), "name": "Hostel", "lost": 0, "found": 1, "recoveries": 0},
        {"location_id": str(loc("lab")), "name": "Laboratories", "lost": 1, "found": 0, "recoveries": 0},
        {"location_id": str(loc("library")), "name": "Library", "lost": 1, "found": 2, "recoveries": 1},
    ]


# ---- monthly trend --------------------------------------------------------------------------------------------
def test_monthly_trend_buckets_by_campus_month_and_report_creation_month(app, db, fixed_now):
    w = World(db)
    w.report("FOUND", created=utc(2026, 4, 5))  # before 'from' -> excluded
    w.report("FOUND", created=utc(2026, 4, 20))  # April
    w.report("FOUND", created=utc(2026, 4, 30, 18, 30))  # 00:00 local on 05-01 -> May
    w.report("FOUND", created=utc(2026, 5, 31, 18, 30))  # 00:00 local on 06-01 -> June
    w.recovery(w.report("FOUND", created=utc(2026, 5, 20), status="RESOLVED"), utc(2026, 6, 2))  # recovered in June, created in May
    w.report("LOST", created=utc(2026, 6, 3))
    db.commit()
    body = get(moderator(app, db), **{"from": "2026-04-10", "to": "2026-06-15"}).json()
    assert body["monthly"] == [
        {"month": "2026-04", "lost": 0, "found": 1, "recoveries": 0},
        {"month": "2026-05", "lost": 0, "found": 2, "recoveries": 1},  # recovery attributed to the report-creation month
        {"month": "2026-06", "lost": 1, "found": 1, "recoveries": 0},
    ]
    assert body["recoveries"] == 1  # event view: completed 06-02, inside the period


def test_monthly_spans_year_boundary(app, db, fixed_now):
    w = World(db)
    w.report("LOST", created=utc(2025, 12, 20))
    w.report("FOUND", created=utc(2026, 1, 10))
    db.commit()
    body = get(moderator(app, db), **{"from": "2025-11-20", "to": "2026-02-10"}).json()
    assert [(m["month"], m["lost"], m["found"]) for m in body["monthly"]] == [
        ("2025-11", 0, 0), ("2025-12", 1, 0), ("2026-01", 0, 1), ("2026-02", 0, 0)]


# ---- privacy / aggregation boundary ---------------------------------------------------------------------------
def test_response_is_aggregate_only_and_leaks_nothing_private(app, db, fixed_now):
    w = World(db)
    found = w.report("FOUND", status="RESOLVED")
    found.title, found.description = "SECRET-TITLE-XYZ", "SECRET-DESCRIPTION-XYZ"
    claim = w.claim(found, status="RECOVERED")
    claim.claim_statement, claim.decision_note, claim.information_request_note = "SECRET-STATEMENT-XYZ", "SECRET-NOTE-XYZ", "SECRET-INFO-XYZ"
    w.recovery(w.report("FOUND", status="RESOLVED"), utc(2026, 6, 5))
    db.commit()
    text = get(moderator(app, db)).text
    for secret in ("SECRET-", w.owner.email_normalized, w.owner.display_name, "Claimant", "password", "token", "csrf", "blob", "storage_key",
                   w.owner.password_hash):
        assert secret.lower() not in text.lower(), secret
    for uid in (w.owner.user_id, w.staff.user_id):
        assert str(uid) not in text


# ---- end to end through the real workflow --------------------------------------------------------------------
def test_end_to_end_report_claim_recovery_flows_into_analytics(app, db):
    finder, claimant, mod = login_api(app, db, name="Finder"), login_api(app, db, name="Claimant"), moderator(app, db)
    found = finder.post("/api/reports", report_body("FOUND")).json()
    bystander = finder.post("/api/reports", report_body("FOUND", title="Still unclaimed item")).json()
    claim = claimant.post(f"/api/reports/{found['report_id']}/claims", {"claim_statement": "It has my initials sewn inside the lining."}).json()["claim"]
    verified = mod.post(f"/api/moderation/claims/{claim['claim_id']}/verify", {"expected_version": claim["version"]}).json()["claim"]
    assert mod.post(f"/api/moderation/claims/{claim['claim_id']}/recover", {"expected_version": verified["version"]}).status_code == 200
    body = get(mod).json()
    assert body["found_reports"] == 2 and body["recovery_rate_pct"] == 50.0 and body["recovery_rate_non_withdrawn_pct"] == 50.0
    assert body["claims"]["submitted"] == 1 and body["claims"]["verified"] == 1 and body["recoveries"] == 1
    assert body["report_status_counts"]["found"]["RESOLVED"] == 1 and body["report_status_counts"]["found"]["ACTIVE"] == 1
    assert body["average_recovery_days"] is not None and 0.0 <= body["average_recovery_days"] < 1.0
    assert sum(m["recoveries"] for m in body["monthly"]) == 1 and body["by_category"][0]["recoveries"] == 1
    assert uuid.UUID(bystander["report_id"]) and "initials" not in str(body)
