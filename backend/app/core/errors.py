"""Stable API error type and envelope (contract §1)."""

from __future__ import annotations


class AppError(Exception):
    def __init__(
        self, status_code: int, code: str, message: str, field_errors: dict[str, list[str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field_errors = field_errors
        self.headers = headers or {}


def bad_request(code: str, message: str) -> AppError:
    return AppError(400, code, message)


def unauthenticated(message: str = "Authentication required.") -> AppError:
    return AppError(401, "UNAUTHENTICATED", message)


def forbidden(message: str = "You do not have permission to perform this action.", code: str = "FORBIDDEN") -> AppError:
    return AppError(403, code, message)


def not_found(message: str = "Resource not found.", code: str = "NOT_FOUND") -> AppError:
    return AppError(404, code, message)


def conflict(code: str, message: str) -> AppError:
    return AppError(409, code, message)


def unprocessable(message: str, field_errors: dict[str, list[str]] | None = None) -> AppError:
    return AppError(422, "VALIDATION_ERROR", message, field_errors)


def unavailable(message: str = "A required service is temporarily unavailable.") -> AppError:
    return AppError(503, "DEPENDENCY_UNAVAILABLE", message)


class DataIntegrityError(RuntimeError):
    """A row that foreign-key constraints guarantee to exist was not found.

    Deliberately not an AppError: it surfaces as the generic 500 envelope, never as a client-visible 4xx.
    """


def require[T](obj: T | None, what: str) -> T:
    """Narrow an Optional ORM lookup whose absence would mean a broken referential invariant."""
    if obj is None:
        raise DataIntegrityError(f"Referenced {what} is missing.")
    return obj
