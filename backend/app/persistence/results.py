"""Typed access to DML statement results."""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import CursorResult, Result


def affected_rows(result: Result[Any]) -> int:
    """Rows affected by an INSERT/UPDATE/DELETE executed through ``Session.execute``.

    SQLAlchemy returns a ``CursorResult`` for DML, but ``Session.execute`` is annotated with the broader
    ``Result`` type, which has no ``rowcount``. Narrow explicitly rather than casting to ``Any``.
    """
    if not isinstance(result, CursorResult):
        raise TypeError("affected_rows() requires the result of a DML statement.")
    return int(result.rowcount)
