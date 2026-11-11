"""Application settings (IMPLEMENTATION_CONTRACTS §15 configuration names)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"), env_file_encoding="utf-8", extra="ignore",
        populate_by_name=True,
    )

    app_env: Literal["development", "production", "test"] = Field(default="development", alias="APP_ENV")
    frontend_origin: str = Field(default="http://localhost:5173", alias="FRONTEND_ORIGIN")
    api_public_origin: str = Field(default="http://localhost:8000", alias="API_PUBLIC_ORIGIN")
    campus_config_path: str = Field(default="config/campus.json", alias="CAMPUS_CONFIG_PATH")
    database_url: str = Field(default="", alias="DATABASE_URL")
    azure_storage_account_url: str = Field(default="", alias="AZURE_STORAGE_ACCOUNT_URL")
    azure_storage_container: str = Field(default="findmything-private", alias="AZURE_STORAGE_CONTAINER")
    # Local development only: directory-backed blob store. Refused in production.
    local_blob_dir: str = Field(default="", alias="LOCAL_BLOB_DIR")
    session_cookie_name: str = Field(default="findmything_session", alias="SESSION_COOKIE_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    # Trust X-Forwarded-For only when explicitly enabled (App Service sets it) - contract §9.
    trust_forwarded_for: bool = Field(default=False, alias="TRUST_FORWARDED_FOR")
    # In-process matching poller (Blueprint 6.1). Jobs are durable in SQL either way; CLI can also run them.
    matching_worker_enabled: bool = Field(default=True, alias="MATCHING_WORKER_ENABLED")
    matching_poll_seconds: float = Field(default=2.0, alias="MATCHING_POLL_SECONDS")

    # Frozen constants (contract §4.1 / §21, Blueprint §6).
    session_max_age_seconds: int = 43200
    last_seen_throttle_seconds: int = 900
    max_upload_bytes: int = 5_000_000
    algorithm_version: str = "match-v1"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.app_env == "production":
            if self.session_cookie_name != "findmything_session":
                raise ValueError("SESSION_COOKIE_NAME must be findmything_session in production")
            if "*" in self.frontend_origin or not self.frontend_origin.startswith("https://"):
                raise ValueError("FRONTEND_ORIGIN must be one exact https origin in production")
            if "trustservercertificate=yes" in self.database_url.lower().replace(" ", ""):
                raise ValueError("TrustServerCertificate must be false in production")
            if self.local_blob_dir:
                raise ValueError("LOCAL_BLOB_DIR is for local development only")
        return self

    def campus_config_file(self) -> Path:
        p = Path(self.campus_config_path)
        return p if p.is_absolute() else REPO_ROOT / p


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_campus_config(path: Path) -> dict:
    """Load and validate campus JSON (contract §7). Fails clearly; never guesses taxonomy."""
    if not path.exists():
        raise FileNotFoundError(
            f"Campus config not found at {path}. Copy config/campus.example.json to config/campus.json and edit it."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("campus_display_name", "timezone", "categories", "zones", "locations"):
        if key not in data:
            raise ValueError(f"Campus config missing required key: {key}")
    from zoneinfo import ZoneInfo

    ZoneInfo(data["timezone"])
    zone_slugs = {z["slug"] for z in data["zones"]}
    for kind in ("categories", "zones", "locations"):
        slugs = [i["slug"] for i in data[kind]]
        names = [i["name"] for i in data[kind]]
        if len(set(slugs)) != len(slugs) or len(set(names)) != len(names):
            raise ValueError(f"Duplicate slug or name in {kind}")
    all_names = [z["name"] for z in data["zones"]] + [x["name"] for x in data["locations"]]
    if len(set(all_names)) != len(all_names):
        raise ValueError("Zone and location names must be unique across both lists")
    for loc in data["locations"]:
        if loc.get("zone_slug") not in zone_slugs:
            raise ValueError(f"Location {loc['slug']} references unknown zone {loc.get('zone_slug')}")
    return data


_campus_cache: dict | None = None


def get_campus_config() -> dict:
    """Validated campus config, loaded once. Tests may preset it via set_campus_config."""
    global _campus_cache
    if _campus_cache is None:
        _campus_cache = load_campus_config(get_settings().campus_config_file())
    return _campus_cache


def set_campus_config(value: dict | None) -> None:
    global _campus_cache
    _campus_cache = value
