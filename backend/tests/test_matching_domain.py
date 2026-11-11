import datetime as dt
import uuid
from decimal import Decimal

from app.domain import matching as m

Z1, Z2 = uuid.uuid4(), uuid.uuid4()
L1, L2, L3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
C1, C2 = uuid.uuid4(), uuid.uuid4()
NOW = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)


def rv(category=C1, location=L1, zone=Z1, day=1, title="Black laptop bag", desc="Black laptop bag with charger inside"):
    return m.ReportView(uuid.uuid4(), category, location, zone, dt.date(2026, 10, day), title, desc, NOW)


def test_weights_sum_to_one():
    assert sum(m.WEIGHTS.values()) == Decimal("1.00")


def test_identical_reports_score_100():
    r = m.score_pair(rv(), rv())
    assert r.total == Decimal("100.00") and r.status == "POTENTIAL"
    assert r.category == r.location == r.date == r.keywords == Decimal("100.00")


def test_category_mismatch_loses_forty_points():
    r = m.score_pair(rv(), rv(category=C2))
    assert r.category == 0 and r.total == Decimal("60.00")


def test_location_rules_exact_zone_other():
    assert m.location_score(rv(), rv()) == 100
    assert m.location_score(rv(), rv(location=L2)) == 60  # same zone
    assert m.location_score(rv(), rv(location=L3, zone=Z2)) == 0


def test_date_linear_decay_and_window():
    assert m.date_score(0) == 100
    assert m.date_score(15) == Decimal("50")
    assert m.date_score(30) == 0
    assert m.in_candidate_window(rv(day=1), rv(day=31)) is True  # exactly 30 days
    far = m.ReportView(uuid.uuid4(), C1, L1, Z1, dt.date(2026, 12, 5), "x", "y", NOW)
    assert m.in_candidate_window(rv(day=1), far) is False


def test_keyword_tokenization_removes_stopwords_and_short_tokens():
    toks = m.tokenize("The Blue Bottle", "A bottle of water, x!")
    assert toks == frozenset({"blue", "bottle", "water"})


def test_empty_keyword_sets_score_zero():
    assert m.jaccard_percent(frozenset(), frozenset({"a1"})) == 0


def test_threshold_boundary_is_inclusive():
    # category 100*.4 + location 60*.25 = 55 -> potential even with no date/keyword help
    r = m.score_pair(rv(location=L2, title="zzzz qqqq", desc="wwww eeee", day=1), rv(location=L1, title="aaaa bbbb", desc="cccc dddd", day=31))
    assert r.date == 0 and r.keywords == 0 and r.total == Decimal("55.00") and r.status == "POTENTIAL"
    # Exactly 50.00 (location 25 + date 25, nothing else) is POTENTIAL: the threshold is inclusive.
    exact = m.score_pair(rv(category=C2, title="zzzz qqqq", desc="wwww eeee"), rv(title="aaaa bbbb", desc="cccc dddd"))
    assert exact.total == Decimal("50.00") and exact.status == "POTENTIAL"
    # Same-zone location (15) + same date (25) = 40 -> SUPPRESSED.
    below = m.score_pair(rv(category=C2, location=L2, title="zzzz qqqq", desc="wwww eeee"), rv(title="aaaa bbbb", desc="cccc dddd"))
    assert below.total == Decimal("40.00") and below.status == "SUPPRESSED"


def test_determinism():
    a, b = rv(), rv(location=L2)
    assert m.score_pair(a, b) == m.score_pair(a, b)


def test_rank_key_orders_score_then_gap_then_location_then_created_then_uuid():
    r_hi = m.score_pair(rv(), rv())
    r_lo = m.score_pair(rv(), rv(category=C2))
    k_hi = m.rank_key(r_hi, Decimal(100), NOW, uuid.UUID(int=2))
    k_lo = m.rank_key(r_lo, Decimal(100), NOW, uuid.UUID(int=1))
    assert k_hi < k_lo
    same = m.rank_key(r_hi, Decimal(100), NOW, uuid.UUID(int=1))
    assert same < k_hi  # equal on everything but UUID -> UUID ascending breaks the tie
