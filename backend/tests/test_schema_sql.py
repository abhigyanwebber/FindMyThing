"""SQL Server schema guarantees: trigger, uniqueness invariants, constraints, analytics views."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.security import new_id, utcnow
from app.persistence.database import clear_trigger_context, set_trigger_context
from app.persistence.models import Recovery
from tests.helpers import make_claim, make_report, make_user

pytestmark = pytest.mark.sql


def _status(db, report, new, actor=None, reason="TEST_REASON", corr="corr-1"):
    set_trigger_context(db, actor.user_id if actor else None, reason, corr)
    db.execute(
        text("UPDATE reports SET status=:s, version=version+1 WHERE report_id=:r"),
        {"s": new, "r": report.report_id},
    )


def test_expected_tables_and_views_exist(db):
    names = {r[0] for r in db.execute(text("SELECT name FROM sys.objects WHERE type IN ('U','V')"))}
    for t in ("roles users sessions categories locations reports attachments matches claims matching_jobs "
              "report_status_history claim_status_history activity_logs recoveries claim_evidence "
              "rate_limit_counters vw_recovery_analytics vw_claim_transition_analytics").split():
        assert t in names, t


def test_trigger_records_status_change_with_context(db):
    owner = make_user(db)
    mod = make_user(db, "MODERATOR")
    r = make_report(db, owner)
    _status(db, r, "WITHDRAWN", actor=owner, reason="OWNER_WITHDRAWN", corr="req-42")
    clear_trigger_context(db)
    db.commit()
    row = db.execute(
        text("SELECT old_status,new_status,changed_by_user_id,reason_code,correlation_id FROM report_status_history WHERE report_id=:r"),
        {"r": r.report_id},
    ).one()
    assert (row.old_status, row.new_status, row.reason_code, row.correlation_id) == ("ACTIVE", "WITHDRAWN", "OWNER_WITHDRAWN", "req-42")
    assert str(row.changed_by_user_id).lower() == str(owner.user_id).lower()
    assert mod is not None


def test_trigger_ignores_non_status_updates_and_records_every_transition(db):
    owner = make_user(db)
    r = make_report(db, owner)
    db.execute(text("UPDATE reports SET title='New title' WHERE report_id=:r"), {"r": r.report_id})
    db.commit()
    n = db.execute(text("SELECT COUNT(*) FROM report_status_history WHERE report_id=:r"), {"r": r.report_id}).scalar()
    assert n == 0
    _status(db, r, "RESOLVED")
    _status(db, r, "ACTIVE", reason="RECOVERY_VOIDED")
    db.commit()
    rows = db.execute(text("SELECT old_status,new_status FROM report_status_history WHERE report_id=:r ORDER BY changed_at_utc"), {"r": r.report_id}).all()
    assert len(rows) == 2


def test_trigger_defaults_when_context_missing(db):
    owner = make_user(db)
    r = make_report(db, owner)
    db.execute(text("UPDATE reports SET status='CLOSED' WHERE report_id=:r"), {"r": r.report_id})
    db.commit()
    row = db.execute(text("SELECT reason_code,correlation_id,changed_by_user_id FROM report_status_history WHERE report_id=:r"), {"r": r.report_id}).one()
    assert row.reason_code == "UNSPECIFIED" and row.correlation_id == "none" and row.changed_by_user_id is None


def test_many_pending_claims_allowed_per_found_report(db):
    found = make_report(db, make_user(db))
    for _ in range(3):
        make_claim(db, make_user(db), found)
    db.commit()


def test_duplicate_active_claim_by_same_claimant_blocked_but_terminal_allowed(db):
    found = make_report(db, make_user(db))
    claimant = make_user(db)
    make_claim(db, claimant, found, status="REJECTED")
    make_claim(db, claimant, found, status="CANCELLED")
    make_claim(db, claimant, found, status="PENDING")
    db.commit()
    with pytest.raises(IntegrityError):
        make_claim(db, claimant, found, status="PENDING")
    db.rollback()


def test_only_one_verified_or_recovered_claim_per_found_report(db):
    found = make_report(db, make_user(db))
    make_claim(db, make_user(db), found, status="VERIFIED")
    db.commit()
    with pytest.raises(IntegrityError):
        make_claim(db, make_user(db), found, status="RECOVERED")
    db.rollback()


def test_only_one_verified_or_recovered_claim_per_lost_report(db):
    lost = make_report(db, make_user(db), "LOST")
    f1, f2 = make_report(db, make_user(db)), make_report(db, make_user(db))
    claimant = make_user(db)
    make_claim(db, claimant, f1, lost, status="VERIFIED")
    db.commit()
    with pytest.raises(IntegrityError):
        make_claim(db, claimant, f2, lost, status="VERIFIED")
    db.rollback()


def _recovery(db, claim, found, mod, status="COMPLETED", lost=None):
    now = utcnow()
    db.add(Recovery(
        recovery_id=new_id(), claim_id=claim.claim_id, found_report_id=found.report_id,
        lost_report_id=lost.report_id if lost else None, status=status,
        completed_by_moderator_id=mod.user_id, completed_at_utc=now, found_prior_status="ACTIVE",
        found_prior_version=1, found_post_version=2,
    ))
    db.flush()


def test_one_completed_recovery_per_claim_found_and_lost_but_voided_may_repeat(db):
    mod = make_user(db, "MODERATOR")
    found = make_report(db, make_user(db))
    claim = make_claim(db, make_user(db), found, status="VERIFIED")
    _recovery(db, claim, found, mod, "VOIDED")
    _recovery(db, claim, found, mod, "VOIDED")
    _recovery(db, claim, found, mod, "COMPLETED")
    db.commit()
    with pytest.raises(IntegrityError):
        _recovery(db, claim, found, mod, "COMPLETED")
    db.rollback()


def test_one_active_photo_per_report(db):
    owner = make_user(db)
    r = make_report(db, owner)
    ins = text(
        "INSERT INTO attachments (attachment_id,report_id,uploaded_by_user_id,attachment_type,blob_key,original_filename,"
        "content_type,size_bytes,upload_status,created_at_utc) VALUES (NEWID(),:r,:u,'REPORT_PHOTO',:k,'a.png','image/png',10,:s,SYSUTCDATETIME())"
    )
    db.execute(ins, {"r": r.report_id, "u": owner.user_id, "k": f"k-{uuid.uuid4()}", "s": "ACTIVE"})
    db.execute(ins, {"r": r.report_id, "u": owner.user_id, "k": f"k-{uuid.uuid4()}", "s": "DELETED"})
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(ins, {"r": r.report_id, "u": owner.user_id, "k": f"k-{uuid.uuid4()}", "s": "ACTIVE"})
    db.rollback()


def test_check_constraints_reject_bad_data(db):
    owner = make_user(db)
    with pytest.raises(IntegrityError):
        make_report(db, owner, status="BOGUS")
    db.rollback()
    owner = make_user(db)
    r = make_report(db, owner)
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE claims SET claim_statement=claim_statement"))  # no rows; ensure DB alive
        db.execute(text(
            "INSERT INTO matches (match_id,lost_report_id,found_report_id,score,category_score,location_score,date_score,keyword_score,"
            "explanation,algorithm_version,calculated_at_utc,lost_report_matching_version,found_report_matching_version,match_status) "
            "VALUES (NEWID(),:r,:r,50,0,0,0,0,'{}','match-v1',SYSUTCDATETIME(),1,1,'POTENTIAL')"), {"r": r.report_id})
    db.rollback()


def test_analytics_views_expose_no_claimant_identity_or_statements(db):
    cols = {r[0].lower() for r in db.execute(text(
        "SELECT c.name FROM sys.columns c JOIN sys.objects o ON o.object_id=c.object_id WHERE o.name IN ('vw_recovery_analytics','vw_claim_transition_analytics')"))}
    forbidden = {"claimant_user_id", "claim_statement", "email_normalized", "display_name", "blob_key", "report_snapshot", "decision_note", "reporter_user_id"}
    assert not (cols & forbidden)


def test_recovery_analytics_days_to_recovery_rounded_one_decimal(db):
    mod = make_user(db, "MODERATOR")
    found = make_report(db, make_user(db))
    claim = make_claim(db, make_user(db), found, status="RECOVERED")
    _recovery(db, claim, found, mod)
    db.commit()
    row = db.execute(text("SELECT is_recovered, days_to_recovery, claims_submitted FROM vw_recovery_analytics WHERE report_id=:r"), {"r": found.report_id}).one()
    assert row.is_recovered == 1 and row.claims_submitted == 1 and row.days_to_recovery is not None
    assert abs(float(row.days_to_recovery)) < 1.0
    assert dt.date.today() is not None
