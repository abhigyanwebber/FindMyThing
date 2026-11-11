from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import text

from tests.api_helpers import login_api, login_existing, report_body

pytestmark = pytest.mark.sql

STMT = "It has my initials sewn inside the lining."


@pytest.fixture()
def app(db):
    from app.main import create_app

    return create_app()


def q(db, sql, **p):
    db.rollback()
    return db.execute(text(sql), p).all()


class Scene:
    """A FOUND report (owner `finder`), a LOST report (owner `claimant`), moderator, and helpers."""

    def __init__(self, app, db, with_lost=True):
        self.app, self.db = app, db
        self.finder = login_api(app, db, name="Finder")
        self.claimant = login_api(app, db, name="Claimant")
        self.other = login_api(app, db, name="Other Student")
        self.mod = login_api(app, db, "MODERATOR", "Mod One")
        self.found = self.finder.post("/api/reports", report_body("FOUND")).json()
        self.lost = self.claimant.post("/api/reports", report_body("LOST")).json() if with_lost else None

    def claim(self, who=None, lost=True, statement=STMT):
        who = who or self.claimant
        body = {"claim_statement": statement}
        if lost and self.lost:
            body["lost_report_id"] = self.lost["report_id"]
        return who.post(f"/api/reports/{self.found['report_id']}/claims", body)

    def verify(self, claim, mod=None, v=None):
        return (mod or self.mod).post(f"/api/moderation/claims/{claim['claim_id']}/verify", {"expected_version": v or claim["version"]})

    def recover(self, claim_id, v, mod=None):
        return (mod or self.mod).post(f"/api/moderation/claims/{claim_id}/recover", {"expected_version": v})


def test_submit_claim_returns_claimant_safe_dto(app, db):
    s = Scene(app, db)
    r = s.claim()
    assert r.status_code == 201
    c = r.json()["claim"]
    assert c["status"] == "PENDING" and c["version"] == 1 and c["claim_statement"] == STMT
    assert c["found_report"]["report_id"] == s.found["report_id"] and c["lost_report"]["report_id"] == s.lost["report_id"]
    assert c["decision"] == {"reason_code": None, "decision_note": None, "reviewed_at_utc": None}
    assert c["information_request"] == {"note": None, "requested_at_utc": None} and c["evidence"] == []
    blob = str(c).lower()
    for leak in ("reviewed_by", "claimant_user_id", "blob", "email", "reviewer"):
        assert leak not in blob
    snap = q(db, "SELECT report_snapshot, found_report_version_at_submission, lost_report_version_at_submission FROM claims")[0]
    assert "email" not in snap[0] and snap[1] == 1 and snap[2] == 1
    assert q(db, "SELECT COUNT(*) FROM activity_logs WHERE event_type='CLAIM_SUBMITTED'")[0][0] == 1
    assert "initials" not in str(q(db, "SELECT metadata FROM activity_logs"))  # statement never audited


@pytest.mark.parametrize("statement", ["too short", " " * 20, "x" * 2001])
def test_claim_statement_validation(app, db, statement):
    s = Scene(app, db)
    assert s.claim(statement=statement).status_code == 422


def test_claim_eligibility_rules(app, db):
    s = Scene(app, db)
    assert s.claim(s.finder, lost=False).status_code == 403  # own report
    assert s.claim(s.mod, lost=False).status_code == 403  # moderators cannot claim
    assert s.other.post(f"/api/reports/{s.lost['report_id']}/claims", {"claim_statement": STMT}).status_code == 409  # LOST target (not claimable)
    assert s.claimant.post(f"/api/reports/{uuid.uuid4()}/claims", {"claim_statement": STMT}).status_code == 404
    bad = s.other.post(f"/api/reports/{s.found['report_id']}/claims", {"claim_statement": STMT, "lost_report_id": s.lost["report_id"]})
    assert bad.status_code == 422 and "lost_report_id" in bad.json()["error"]["field_errors"]  # not their LOST report
    assert s.claimant.post(f"/api/reports/{s.found['report_id']}/claims", {"claim_statement": STMT, "lost_report_id": s.found["report_id"]}).status_code == 422
    assert s.claim().status_code == 201
    dup = s.claim()
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_ACTIVE_CLAIM"
    assert s.claim(s.other, lost=False).status_code == 201  # many PENDING claims per FOUND are allowed


def test_withdrawn_found_report_hidden_and_not_claimable(app, db):
    s = Scene(app, db)
    s.finder.post(f"/api/reports/{s.found['report_id']}/withdraw", {"expected_version": 1})
    assert s.claim(lost=False).status_code == 404


def test_claim_privacy_report_owner_and_others_cannot_see_claims(app, db):
    s = Scene(app, db)
    c = s.claim().json()["claim"]
    assert s.finder.get(f"/api/claims/{c['claim_id']}").status_code == 404
    assert s.other.get(f"/api/claims/{c['claim_id']}").status_code == 404
    assert s.finder.get("/api/me/claims").json()["total"] == 0
    detail = s.finder.get(f"/api/reports/{s.found['report_id']}").json()
    assert detail["claim_activity"] == {"has_active_claim": True} and "claimant" not in str(detail).lower()
    assert s.claimant.get(f"/api/claims/{c['claim_id']}").status_code == 200
    mine = s.claimant.get("/api/me/claims").json()
    assert mine["total"] == 1 and mine["items"][0]["claim_id"] == c["claim_id"]
    assert s.finder.post(f"/api/moderation/claims/{c['claim_id']}/verify", {"expected_version": 1}).status_code == 403


def test_cancel_pending_and_verified_claim(app, db):
    s = Scene(app, db)
    c = s.claim().json()["claim"]
    assert s.other.post(f"/api/claims/{c['claim_id']}/cancel", {"expected_version": 1}).status_code == 404
    assert s.claimant.post(f"/api/claims/{c['claim_id']}/cancel", {"expected_version": 9}).status_code == 409
    ok = s.claimant.post(f"/api/claims/{c['claim_id']}/cancel", {"expected_version": 1}).json()["claim"]
    assert ok["status"] == "CANCELLED" and ok["version"] == 2 and ok["decision"]["reason_code"] == "CLAIMANT_CANCELLED"
    assert s.claimant.post(f"/api/claims/{c['claim_id']}/cancel", {"expected_version": 2}).status_code == 409
    c2 = s.claim().json()["claim"]  # a new claim is allowed after cancellation
    s.verify(c2)
    v = s.claimant.post(f"/api/claims/{c2['claim_id']}/cancel", {"expected_version": 2}).json()["claim"]
    assert v["status"] == "CANCELLED"
    h = q(db, "SELECT old_status,new_status,reason_code FROM claim_status_history ORDER BY changed_at_utc")
    assert [tuple(x) for x in h] == [("PENDING", "CANCELLED", "CLAIMANT_CANCELLED"), ("PENDING", "VERIFIED", "OWNERSHIP_CONFIRMED"),
                                     ("VERIFIED", "CANCELLED", "CLAIMANT_CANCELLED")]


def test_moderator_list_detail_and_audit(app, db):
    s = Scene(app, db)
    c1 = s.claim().json()["claim"]
    s.claim(s.other, lost=False)
    ml = s.mod.get("/api/moderation/claims").json()
    assert ml["total"] == 2 and "claim_statement" not in str(ml)
    assert s.mod.get("/api/moderation/claims?status=VERIFIED").json()["total"] == 0
    assert s.mod.get("/api/moderation/claims?status=NOPE").status_code == 422
    assert s.mod.get("/api/moderation/claims?bogus=1").status_code == 422
    assert s.claimant.get("/api/moderation/claims").status_code == 403
    d = s.mod.get(f"/api/moderation/claims/{c1['claim_id']}").json()["claim"]
    assert d["claimant"]["email"] and d["claimant"]["display_name"] == "Claimant" and d["claim_statement"] == STMT
    assert d["history"] == [] and d["related_reports"]["found"]["title"] and "blob" not in str(d).lower()
    assert q(db, "SELECT COUNT(*) FROM activity_logs WHERE event_type='MODERATOR_CLAIM_DETAIL_ACCESSED'")[0][0] == 1
    assert s.claimant.get(f"/api/moderation/claims/{c1['claim_id']}").status_code == 403


def test_verify_reject_revoke_rules(app, db):
    s = Scene(app, db)
    c = s.claim().json()["claim"]
    other = s.claim(s.other, lost=False).json()["claim"]  # competing PENDING claim, submitted before any verification
    third = s.claim(login_api(app, db), lost=False).json()["claim"]  # a third PENDING claim for the reject checks
    assert s.verify(c, v=5).status_code == 409
    v = s.verify(c)
    assert v.status_code == 200 and v.json()["claim"]["status"] == "VERIFIED" and v.json()["claim"]["decision"]["reason_code"] == "OWNERSHIP_CONFIRMED"
    assert "reviewer" not in str(v.json()).lower()
    assert s.verify(v.json()["claim"], v=2).status_code == 409  # already verified
    late = s.claim(login_api(app, db), lost=False)  # a verification winner exists: new claims are refused
    assert late.status_code == 409 and late.json()["error"]["code"] == "REPORT_NOT_ELIGIBLE"
    clash = s.verify(other)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "CLAIM_CONFLICT"
    assert s.mod.post(f"/api/moderation/claims/{c['claim_id']}/reject", {"reason_code": "INSUFFICIENT_EVIDENCE", "expected_version": 2}).status_code == 409  # not PENDING
    rv = s.mod.post(f"/api/moderation/claims/{c['claim_id']}/revoke-verification", {"expected_version": 2, "decision_note": "Photo mismatch"})
    assert rv.status_code == 200 and rv.json()["claim"]["status"] == "REJECTED"
    assert rv.json()["claim"]["decision"]["reason_code"] == "VERIFICATION_REVOKED" and rv.json()["claim"]["decision"]["decision_note"] == "Photo mismatch"
    assert s.verify(other).status_code == 200  # winner slot freed
    bad = [("NOPE", None), ("OTHER", None)]
    for reason, note in bad:
        assert s.mod.post(f"/api/moderation/claims/{third['claim_id']}/reject", {"reason_code": reason, "decision_note": note, "expected_version": 1}).status_code == 422
    rj = s.mod.post(f"/api/moderation/claims/{third['claim_id']}/reject", {"reason_code": "INSUFFICIENT_EVIDENCE", "expected_version": 1})
    assert rj.status_code == 200 and rj.json()["claim"]["status"] == "REJECTED"


def test_verification_requires_active_reports_and_lost_ownership(app, db):
    s = Scene(app, db)
    c = s.claim().json()["claim"]
    s.claimant.post(f"/api/reports/{s.lost['report_id']}/withdraw", {"expected_version": 1}) if False else None
    db.execute(text("UPDATE reports SET status='WITHDRAWN' WHERE report_id=:r"), {"r": s.lost["report_id"]})
    db.commit()
    r = s.verify(c)
    assert r.status_code == 409 and r.json()["error"]["code"] == "REPORT_NOT_ELIGIBLE"
    assert q(db, "SELECT status FROM claims")[0][0] == "PENDING"  # unchanged on conflict


def test_request_information_semantics(app, db):
    s = Scene(app, db)
    c = s.claim().json()["claim"]
    before = q(db, "SELECT status_changed_at_utc FROM claims")[0][0]
    assert s.mod.post(f"/api/moderation/claims/{c['claim_id']}/request-information", {"decision_note": "short", "expected_version": 1}).status_code == 422
    r = s.mod.post(f"/api/moderation/claims/{c['claim_id']}/request-information", {"decision_note": "Please describe the charger brand.", "expected_version": 1})
    cl = r.json()["claim"]
    assert r.status_code == 200 and cl["status"] == "PENDING" and cl["version"] == 2
    assert cl["information_request"]["note"] == "Please describe the charger brand."
    assert q(db, "SELECT status_changed_at_utc FROM claims")[0][0] == before  # no status change
    assert "charger" not in str(q(db, "SELECT metadata FROM activity_logs"))  # note not in audit metadata
    assert s.claimant.get(f"/api/claims/{c['claim_id']}").json()["claim"]["information_request"]["note"]
    s.verify(cl)
    assert s.mod.post(f"/api/moderation/claims/{c['claim_id']}/request-information", {"decision_note": "Another question here.", "expected_version": 3}).status_code == 409


def full_recovery(s):
    c = s.claim().json()["claim"]
    v = s.verify(c).json()["claim"]
    return c, v


def test_recovery_resolves_reports_rejects_competitors_and_records_history(app, db):
    s = Scene(app, db)
    comp = s.claim(s.other, lost=False).json()["claim"]
    c, v = full_recovery(s)
    r = s.recover(c["claim_id"], v["version"])
    assert r.status_code == 200
    body = r.json()
    assert body["claim"]["status"] == "RECOVERED" and body["claim"]["version"] == 3
    assert set(body["resolved_reports"]) == {s.found["report_id"], s.lost["report_id"]}
    assert body["recovery"]["status"] == "COMPLETED"
    for rid in body["resolved_reports"]:
        assert s.finder.get(f"/api/reports/{rid}").json()["status"] == "RESOLVED"
    # competing claim: system rejection with the canonical reason and claimant-safe note
    cc = s.other.get(f"/api/claims/{comp['claim_id']}").json()["claim"]
    assert cc["status"] == "REJECTED" and cc["decision"]["reason_code"] == "OTHER_CLAIM_RECOVERED"
    assert cc["decision"]["decision_note"] == "A competing claim completed recovery."
    sys_hist = q(db, "SELECT changed_by_user_id, reason_code FROM claim_status_history WHERE claim_id=:c", c=comp["claim_id"])
    assert sys_hist[0][0] is None and sys_hist[0][1] == "OTHER_CLAIM_RECOVERED"
    # report history written by the trigger with RECOVERY_COMPLETED + moderator actor
    rh = q(db, "SELECT old_status,new_status,reason_code FROM report_status_history WHERE reason_code='RECOVERY_COMPLETED'")
    assert len(rh) == 2 and all(tuple(x)[:2] == ("ACTIVE", "RESOLVED") for x in rh)
    rec = q(db, "SELECT found_prior_status,found_prior_version,found_post_version,lost_prior_status FROM recoveries")[0]
    assert tuple(rec) == ("ACTIVE", 1, 2, "ACTIVE")
    # verification reviewer fields are not overwritten by recovery
    row = q(db, "SELECT reviewed_by_user_id, decision_reason_code FROM claims WHERE claim_id=:c", c=c["claim_id"])[0]
    assert row[1] == "OWNERSHIP_CONFIRMED"
    # matches involving the resolved reports are invalidated; analytics reflect the recovery
    assert q(db, "SELECT COUNT(*) FROM matches WHERE match_status NOT IN ('INVALIDATED')")[0][0] == 0
    assert q(db, "SELECT is_recovered FROM vw_recovery_analytics WHERE report_id=:r", r=s.found["report_id"])[0][0] == 1
    # recovery status is public through the report; claimant identity is not
    pub = s.other.get(f"/api/reports/{s.found['report_id']}").json()
    assert pub["status"] == "RESOLVED" and "Claimant" not in str(pub)


def test_recovery_preconditions(app, db):
    s = Scene(app, db)
    c = s.claim().json()["claim"]
    assert s.recover(c["claim_id"], 1).status_code == 409  # still PENDING
    v = s.verify(c).json()["claim"]
    assert s.recover(c["claim_id"], 99).status_code == 409  # stale version
    assert s.claimant.post(f"/api/moderation/claims/{c['claim_id']}/recover", {"expected_version": 2}).status_code == 403
    db.execute(text("UPDATE reports SET status='CLOSED' WHERE report_id=:r"), {"r": s.found["report_id"]})
    db.commit()
    assert s.recover(c["claim_id"], v["version"]).status_code == 409
    assert q(db, "SELECT COUNT(*) FROM recoveries")[0][0] == 0  # no partial writes


def test_void_recovery_reopens_untouched_reports_and_allows_new_recovery(app, db):
    s = Scene(app, db)
    c, v = full_recovery(s)
    rec = s.recover(c["claim_id"], v["version"]).json()
    rid, cv = rec["recovery"]["recovery_id"], rec["claim"]["version"]
    assert s.mod.post(f"/api/moderation/recoveries/{rid}/void", {"decision_note": "", "expected_claim_version": cv}).status_code == 422
    assert s.mod.post(f"/api/moderation/recoveries/{rid}/void", {"decision_note": "Wrong person collected it", "expected_claim_version": 1}).status_code == 409
    assert s.claimant.post(f"/api/moderation/recoveries/{rid}/void", {"decision_note": "x", "expected_claim_version": cv}).status_code == 403
    out = s.mod.post(f"/api/moderation/recoveries/{rid}/void", {"decision_note": "Wrong person collected it", "expected_claim_version": cv})
    assert out.status_code == 200
    b = out.json()
    assert b["claim"]["status"] == "VERIFIED" and b["recovery"]["status"] == "VOIDED"
    assert set(b["reopened_reports"]) == {s.found["report_id"], s.lost["report_id"]} and b["reports_requiring_reconciliation"] == []
    assert s.finder.get(f"/api/reports/{s.found['report_id']}").json()["status"] == "ACTIVE"
    assert q(db, "SELECT COUNT(*) FROM matching_jobs WHERE status='PENDING'")[0][0] >= 2  # matching resumed
    assert s.mod.post(f"/api/moderation/recoveries/{rid}/void", {"decision_note": "again", "expected_claim_version": b["claim"]["version"]}).status_code == 409
    again = s.recover(c["claim_id"], b["claim"]["version"])
    assert again.status_code == 200  # a voided attempt followed by a new recovery
    assert q(db, "SELECT COUNT(*) FROM recoveries")[0][0] == 2


def test_void_leaves_reports_changed_since_recovery_for_reconciliation(app, db):
    s = Scene(app, db)
    c, v = full_recovery(s)
    rec = s.recover(c["claim_id"], v["version"]).json()
    fv = s.finder.get(f"/api/reports/{s.found['report_id']}").json()["version"]
    s.mod.post(f"/api/moderation/reports/{s.found['report_id']}/correct", {"title": "Corrected found title", "expected_version": fv})
    out = s.mod.post(f"/api/moderation/recoveries/{rec['recovery']['recovery_id']}/void",
                     {"decision_note": "Recovery was recorded in error", "expected_claim_version": rec["claim"]["version"]}).json()
    assert out["reports_requiring_reconciliation"] == [s.found["report_id"]] and out["reopened_reports"] == [s.lost["report_id"]]
    assert s.finder.get(f"/api/reports/{s.found['report_id']}").json()["status"] == "RESOLVED"


def test_moderator_close_blocked_until_claims_terminalized(app, db):
    s = Scene(app, db)
    c = s.claim().json()["claim"]
    fv = s.finder.get(f"/api/reports/{s.found['report_id']}").json()["version"]
    assert s.mod.post(f"/api/moderation/reports/{s.found['report_id']}/close", {"reason_code": "INVALID_REPORT", "expected_version": fv}).status_code == 409
    s.mod.post(f"/api/moderation/claims/{c['claim_id']}/reject", {"reason_code": "INSUFFICIENT_EVIDENCE", "expected_version": 1})
    assert s.mod.post(f"/api/moderation/reports/{s.found['report_id']}/close", {"reason_code": "INVALID_REPORT", "expected_version": fv}).status_code == 200


# ----------------------------------------------------------------- concurrency (real threads, real SQL Server)

def run_parallel(fns):
    barrier = threading.Barrier(len(fns))
    out: list = [None] * len(fns)

    def wrap(i, fn):
        barrier.wait()
        out[i] = fn()

    ts = [threading.Thread(target=wrap, args=(i, f)) for i, f in enumerate(fns)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


@pytest.mark.parametrize("round_", range(3))
def test_race_withdraw_vs_claim_submission(app, db, round_):
    s = Scene(app, db, with_lost=False)
    owner2 = login_existing(app, s.finder.user)
    res = run_parallel([
        lambda: owner2.post(f"/api/reports/{s.found['report_id']}/withdraw", {"expected_version": 1}),
        lambda: s.claim(lost=False),
    ])
    codes = sorted(r.status_code for r in res)
    withdrawn = q(db, "SELECT status FROM reports WHERE report_id=:r", r=s.found["report_id"])[0][0] == "WITHDRAWN"
    claims = q(db, "SELECT COUNT(*) FROM claims")[0][0]
    assert not (withdrawn and claims), "claim exists on a withdrawn report"
    assert codes in ([200, 409], [201, 409], [200, 404]), codes  # exactly one winner, loser sees 409/404
    assert 500 not in codes


@pytest.mark.parametrize("round_", range(3))
def test_race_cancel_vs_recover(app, db, round_):
    s = Scene(app, db, with_lost=False)
    c = s.claim(lost=False).json()["claim"]
    v = s.verify(c).json()["claim"]
    claimant2, mod2 = login_existing(app, s.claimant.user), login_existing(app, s.mod.user)
    res = run_parallel([
        lambda: claimant2.post(f"/api/claims/{c['claim_id']}/cancel", {"expected_version": v["version"]}),
        lambda: s.recover(c["claim_id"], v["version"], mod=mod2),
    ])
    assert sorted(r.status_code for r in res) == [200, 409], [r.text for r in res]
    status = q(db, "SELECT status FROM claims")[0][0]
    resolved = q(db, "SELECT status FROM reports WHERE report_id=:r", r=s.found["report_id"])[0][0]
    assert (status, resolved) in (("CANCELLED", "ACTIVE"), ("RECOVERED", "RESOLVED"))  # never a mixed state


def test_race_double_recovery_has_single_winner(app, db):
    s = Scene(app, db, with_lost=False)
    c = s.claim(lost=False).json()["claim"]
    v = s.verify(c).json()["claim"]
    mods = [login_existing(app, s.mod.user) for _ in range(3)]
    res = run_parallel([lambda m=m: s.recover(c["claim_id"], v["version"], mod=m) for m in mods])
    assert sorted(r.status_code for r in res) == [200, 409, 409]
    assert q(db, "SELECT COUNT(*) FROM recoveries WHERE status='COMPLETED'")[0][0] == 1
    assert q(db, "SELECT COUNT(*) FROM report_status_history WHERE new_status='RESOLVED'")[0][0] == 1


def test_race_two_moderators_verify_competing_claims(app, db):
    s = Scene(app, db, with_lost=False)
    a = s.claim(lost=False).json()["claim"]
    b = s.claim(s.other, lost=False).json()["claim"]
    m2 = login_existing(app, s.mod.user)
    res = run_parallel([lambda: s.verify(a), lambda: s.verify(b, mod=m2)])
    assert sorted(r.status_code for r in res) == [200, 409], [r.text for r in res]
    assert q(db, "SELECT COUNT(*) FROM claims WHERE status='VERIFIED'")[0][0] == 1


def test_race_same_claimant_double_submit_creates_one_claim(app, db):
    s = Scene(app, db, with_lost=False)
    sessions = [login_existing(app, s.claimant.user) for _ in range(4)]
    res = run_parallel([lambda x=x: s.claim(x, lost=False) for x in sessions])
    assert sorted(r.status_code for r in res) == [201, 409, 409, 409]
    assert q(db, "SELECT COUNT(*) FROM claims")[0][0] == 1


def test_race_verify_vs_reject_same_claim(app, db):
    s = Scene(app, db, with_lost=False)
    c = s.claim(lost=False).json()["claim"]
    m2 = login_existing(app, s.mod.user)
    res = run_parallel([
        lambda: s.verify(c),
        lambda: m2.post(f"/api/moderation/claims/{c['claim_id']}/reject", {"reason_code": "INSUFFICIENT_EVIDENCE", "expected_version": c["version"]}),
    ])
    assert sorted(r.status_code for r in res) == [200, 409]
    assert q(db, "SELECT COUNT(*) FROM claim_status_history WHERE claim_id=:c", c=c["claim_id"])[0][0] == 1
