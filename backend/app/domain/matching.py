"""Deterministic `match-v1` scoring (Blueprint §6, contracts §8). Pure functions; no I/O.

Documented implementation assumptions (spec leaves exact arithmetic open):
* Factor scores and the weighted total are computed with ``Decimal`` at high precision and
  quantized to 2 places (ROUND_HALF_UP) to match the persisted ``decimal(5,2)`` columns.
* The 50-point POTENTIAL threshold is applied to the quantized (persisted) total so the stored
  score and stored status can never disagree.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 40

ALGORITHM_VERSION = "match-v1"
THRESHOLD = Decimal("50")
DATE_WINDOW_DAYS = 30
WEIGHTS = {
    "category": Decimal("0.40"),
    "location": Decimal("0.25"),
    "date": Decimal("0.25"),
    "keywords": Decimal("0.10"),
}
TWO_PLACES = Decimal("0.01")

# Fixed, documented English stopword list (Blueprint §6.3). Changing it requires a new algorithm version.
STOPWORDS = frozenset(
    """a about above after again all also am an and any are as at be because been before being below
    between both but by can could did do does doing down during each few for from further had has have
    having he her here hers herself him himself his how i if in into is it its itself just me more most
    my myself no nor not now of off on once only or other our ours ourselves out over own same she should
    so some such than that the their theirs them themselves then there these they this those through to
    too under until up very was we were what when where which while who whom why will with would you your
    yours yourself yourselves""".split()
)

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def tokenize(title: str, description: str) -> frozenset[str]:
    text = unicodedata.normalize("NFKC", f"{title} {description}").casefold()
    return frozenset(t for t in _TOKEN.findall(text) if len(t) >= 2 and t not in STOPWORDS)


def jaccard_percent(a: frozenset[str], b: frozenset[str]) -> Decimal:
    if not a or not b:
        return Decimal(0)
    union = len(a | b)
    return (Decimal(len(a & b)) / Decimal(union)) * 100 if union else Decimal(0)


def q2(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ReportView:
    report_id: uuid.UUID
    category_id: uuid.UUID
    location_id: uuid.UUID
    zone_id: uuid.UUID  # the location's zone (a zone row's own id if the location is a zone)
    occurred_on: dt.date
    title: str
    description: str
    created_at_utc: dt.datetime


@dataclass(frozen=True)
class MatchResult:
    total: Decimal
    category: Decimal
    location: Decimal
    date: Decimal
    keywords: Decimal
    date_gap_days: int
    status: str  # POTENTIAL | SUPPRESSED
    explanation: dict[str, str]


def category_score(lost: ReportView, found: ReportView) -> Decimal:
    return Decimal(100) if lost.category_id == found.category_id else Decimal(0)


def location_score(lost: ReportView, found: ReportView) -> Decimal:
    if lost.location_id == found.location_id:
        return Decimal(100)
    if lost.zone_id == found.zone_id:
        return Decimal(60)
    return Decimal(0)


def date_gap(lost: ReportView, found: ReportView) -> int:
    return abs((lost.occurred_on - found.occurred_on).days)


def date_score(gap_days: int) -> Decimal:
    return max(Decimal(0), Decimal(100) * (Decimal(1) - Decimal(gap_days) / Decimal(DATE_WINDOW_DAYS)))


def in_candidate_window(lost: ReportView, found: ReportView) -> bool:
    return date_gap(lost, found) <= DATE_WINDOW_DAYS


def score_pair(lost: ReportView, found: ReportView) -> MatchResult:
    """Score one LOST/FOUND pair. Caller must have applied eligibility + 30-day window filters."""
    gap = date_gap(lost, found)
    cat = q2(category_score(lost, found))
    loc = q2(location_score(lost, found))
    dat = q2(date_score(gap))
    kw = q2(jaccard_percent(tokenize(lost.title, lost.description), tokenize(found.title, found.description)))
    total = q2(
        category_score(lost, found) * WEIGHTS["category"]
        + location_score(lost, found) * WEIGHTS["location"]
        + date_score(gap) * WEIGHTS["date"]
        + jaccard_percent(tokenize(lost.title, lost.description), tokenize(found.title, found.description)) * WEIGHTS["keywords"]
    )
    status = "POTENTIAL" if total >= THRESHOLD else "SUPPRESSED"
    explanation = {
        "category": "Same category (100)." if cat == 100 else "Different category (0).",
        "location": {
            Decimal(100): "Same location (100).",
            Decimal(60): "Different location in the same zone (60).",
        }.get(loc, "Different zone (0)."),
        "date": f"Events {gap} day(s) apart; linear decay over {DATE_WINDOW_DAYS} days ({dat}).",
        "keywords": f"Shared-keyword (Jaccard) similarity {kw}.",
    }
    return MatchResult(total, cat, loc, dat, kw, gap, status, explanation)


def rank_key(result: MatchResult, location: Decimal, counterpart_created: dt.datetime, counterpart_id: uuid.UUID):
    """Sort key: score DESC, date gap ASC, location DESC, created ASC, UUID ASC (Blueprint §6.4)."""
    return (-result.total, result.date_gap_days, -location, counterpart_created, str(counterpart_id))
