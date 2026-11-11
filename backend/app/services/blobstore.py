"""Private Blob storage adapters (contract §9, §21, §23, §24).

Production uses azure-storage-blob + DefaultAzureCredential (managed identity); no account keys.
LOCAL_BLOB_DIR selects a directory-backed store for local development and tests only (refused in production).
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings
from app.core.errors import unavailable

log = logging.getLogger("findmything.blob")
_KEY_RE = re.compile(r"^attachments/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.(jpg|png|webp)$")


class BlobUnavailableError(Exception):
    """Storage failed for a reason other than 'not found'."""


class BlobNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class BlobInfo:
    key: str
    last_modified: dt.datetime


class BlobStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...  # a missing blob counts as success
    def list(self, prefix: str = "attachments/") -> Iterator[BlobInfo]: ...


def validate_key(key: str) -> str:
    if not _KEY_RE.match(key):
        raise ValueError("Invalid blob key")
    return key


class LocalBlobStore:
    """Directory-backed store. Development/test only."""

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / validate_key(key)).resolve()
        if self.root not in p.parents:
            raise ValueError("Path traversal rejected")
        return p

    def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise BlobNotFoundError(key) from exc

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass

    def list(self, prefix: str = "attachments/") -> Iterator[BlobInfo]:
        base = self.root / prefix
        if not base.exists():
            return
        for f in base.iterdir():
            if f.is_file():
                yield BlobInfo(f"{prefix}{f.name}", dt.datetime.fromtimestamp(f.stat().st_mtime, tz=dt.timezone.utc))


class AzureBlobStore:
    def __init__(self, account_url: str, container: str) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        self._container = BlobServiceClient(account_url, credential=DefaultAzureCredential()).get_container_client(container)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        from azure.core.exceptions import AzureError
        from azure.storage.blob import ContentSettings

        try:
            self._container.upload_blob(validate_key(key), data, overwrite=False, content_settings=ContentSettings(content_type=content_type))
        except AzureError as exc:
            log.error("blob upload failed: %s", type(exc).__name__)
            raise BlobUnavailableError from exc

    def get(self, key: str) -> bytes:
        from azure.core.exceptions import AzureError, ResourceNotFoundError

        try:
            return self._container.download_blob(validate_key(key)).readall()
        except ResourceNotFoundError as exc:
            raise BlobNotFoundError(key) from exc
        except AzureError as exc:
            log.error("blob download failed: %s", type(exc).__name__)
            raise BlobUnavailableError from exc

    def delete(self, key: str) -> None:
        from azure.core.exceptions import AzureError, ResourceNotFoundError

        try:
            self._container.delete_blob(validate_key(key))
        except ResourceNotFoundError:
            return  # 404 is success (contract §24)
        except AzureError as exc:
            log.error("blob delete failed: %s", type(exc).__name__)
            raise BlobUnavailableError from exc

    def list(self, prefix: str = "attachments/") -> Iterator[BlobInfo]:
        from azure.core.exceptions import AzureError

        try:
            for b in self._container.list_blobs(name_starts_with=prefix):
                yield BlobInfo(b.name, b.last_modified)
        except AzureError as exc:
            raise BlobUnavailableError from exc


_store: BlobStore | None = None


def get_blob_store() -> BlobStore:
    """Resolve the configured store lazily so the app starts (and reports readiness) without Azure."""
    global _store
    if _store is not None:
        return _store
    s = get_settings()
    if s.local_blob_dir and not s.is_production:
        _store = LocalBlobStore(s.local_blob_dir)
    elif s.azure_storage_account_url:
        _store = AzureBlobStore(s.azure_storage_account_url, s.azure_storage_container)
    else:
        raise unavailable("File storage is not configured.")
    return _store


def set_blob_store(store: BlobStore | None) -> None:
    global _store
    _store = store


_ = os
