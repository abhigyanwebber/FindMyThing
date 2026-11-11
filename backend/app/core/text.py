"""Text normalization and validation rules (contract §2)."""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from zoneinfo import ZoneInfo

from app.core.errors import unprocessable

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_WS = re.compile(r"\s+")
_EMAIL = re.compile(  # noqa: E501
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


def clean_text(value: str, *, field: str, min_len: int, max_len: int, collapse: bool = True) -> str:
    """Trim, reject control chars (other than ordinary whitespace), normalize, enforce code-point length."""
    if not isinstance(value, str):
        raise unprocessable("Invalid value.", {field: ["Must be text."]})
    value = unicodedata.normalize("NFC", value)
    if _CONTROL.search(value):
        raise unprocessable("Invalid characters.", {field: ["Contains control characters."]})
    value = value.strip()
    if collapse:
        value = _WS.sub(" ", value)
    if not value:
        raise unprocessable("Value required.", {field: ["Must not be blank."]})
    if not (min_len <= len(value) <= max_len):
        raise unprocessable(
            "Invalid length.", {field: [f"Must be between {min_len} and {max_len} characters."]}
        )
    return value


def clean_optional_note(value: str | None, *, field: str = "decision_note", max_len: int = 1000) -> str | None:
    if value is None:
        return None
    value = unicodedata.normalize("NFC", value)
    if _CONTROL.search(value):
        raise unprocessable("Invalid characters.", {field: ["Contains control characters."]})
    value = _WS.sub(" ", value.strip())
    if not value:
        return None
    if len(value) > max_len:
        raise unprocessable("Too long.", {field: [f"Must be at most {max_len} characters."]})
    return value


def normalize_email(value: str) -> str:
    if not isinstance(value, str):
        raise unprocessable("Invalid email.", {"email": ["Must be text."]})
    email = value.strip().lower()
    if not (3 <= len(email) <= 254) or not _EMAIL.match(email) or ".." in email:
        raise unprocessable("Invalid email.", {"email": ["Enter a valid email address."]})
    return email


def validate_password(value: str) -> str:
    if not isinstance(value, str) or not (12 <= len(value) <= 128):
        raise unprocessable("Invalid password.", {"password": ["Must be between 12 and 128 characters."]})
    if not value.strip():
        raise unprocessable("Invalid password.", {"password": ["Must not be only whitespace."]})
    return value  # never trimmed


def _ten_years_before(today: dt.date) -> dt.date:
    try:
        return today.replace(year=today.year - 10)
    except ValueError:  # Feb 29 -> Feb 28
        return today.replace(year=today.year - 10, day=28)


def validate_occurred_on(value: dt.date, campus_tz: str) -> dt.date:
    today = dt.datetime.now(ZoneInfo(campus_tz)).date()
    earliest = _ten_years_before(today)
    if value > today + dt.timedelta(days=1):
        raise unprocessable("Invalid date.", {"occurred_on": ["Date cannot be in the future."]})
    if value < earliest:
        raise unprocessable("Invalid date.", {"occurred_on": ["Date is too far in the past."]})
    return value
