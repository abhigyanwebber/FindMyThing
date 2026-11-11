"""Password hashing, opaque tokens, digests (Blueprint §7.1, contract §4.1)."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi's PasswordHasher defaults to Argon2id with RFC 9106 low-memory parameters
# (>= OWASP minimum). No custom weakening.
_hasher = PasswordHasher()

SEED_NAMESPACE = uuid.UUID("6f1c2b0e-3f55-5c0b-9d0a-4e6c1d2f8a11")  # fixed namespace for UUIDv5 seed IDs


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def seed_id(kind: str, slug: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"{kind}:{slug}")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


# Pre-computed once so login timing is similar for unknown emails.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-equalization")


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def new_token() -> str:
    """32 random bytes, URL-safe base64 without padding (contract §4.1)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii", errors="ignore")).digest()


def constant_time_equal(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)


def key_hash(*parts: str) -> bytes:
    """SHA-256 of a composite rate-limit key; raw email/IP is never stored."""
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
