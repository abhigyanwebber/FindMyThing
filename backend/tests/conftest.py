"""Test harness. Integration tests run against REAL SQL Server (contract §13): no SQLite substitution.

Requires a SQL Server reachable via TEST_ADMIN_DATABASE_URL (see backend/.env.example). A throwaway
database `findmything_test` is dropped, recreated and migrated with Alembic once per session.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest
from dotenv import dotenv_values

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_env = dotenv_values(BACKEND / ".env")
ADMIN_URL = os.environ.get("TEST_ADMIN_DATABASE_URL") or _env.get("TEST_ADMIN_DATABASE_URL")
TEST_DB = "findmything_test"

os.environ["APP_ENV"] = "test"
os.environ["MATCHING_WORKER_ENABLED"] = "false"  # tests drive the worker explicitly
os.environ["FRONTEND_ORIGIN"] = "http://localhost:5173"
os.environ["API_PUBLIC_ORIGIN"] = "http://localhost:8000"
os.environ.pop("LOCAL_BLOB_DIR", None)
if ADMIN_URL:
    os.environ["DATABASE_URL"] = ADMIN_URL.replace("Database=master", f"Database={TEST_DB}")

CAMPUS = {
    "campus_display_name": "Test Campus", "timezone": "Asia/Kolkata",
    "categories": [{"slug": "electronics", "name": "Electronics"}, {"slug": "bags", "name": "Bags"}, {"slug": "other", "name": "Other"}],
    "zones": [{"slug": "academic-zone", "name": "Academic Zone"}, {"slug": "residential-zone", "name": "Residential Zone"}],
    "locations": [
        {"slug": "library", "name": "Library", "zone_slug": "academic-zone"},
        {"slug": "lab", "name": "Laboratories", "zone_slug": "academic-zone"},
        {"slug": "hostel", "name": "Hostel", "zone_slug": "residential-zone"},
    ],
}

DELETE_ORDER = [
    "rate_limit_counters", "claim_evidence", "recoveries", "activity_logs", "claim_status_history",
    "report_status_history", "matching_jobs", "matches", "claims", "attachments", "reports",
    "sessions", "users",
]


def pytest_collection_modifyitems(config, items):
    if ADMIN_URL:
        return
    skip = pytest.mark.skip(reason="TEST_ADMIN_DATABASE_URL not set; SQL Server integration tests skipped")
    for item in items:
        if "sql" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def sql_database():
    import pyodbc
    from alembic import command
    from alembic.config import Config

    admin = pyodbc.connect(ADMIN_URL, autocommit=True)
    admin.execute(
        f"IF DB_ID('{TEST_DB}') IS NOT NULL BEGIN ALTER DATABASE [{TEST_DB}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{TEST_DB}]; END"
    )
    admin.execute(f"CREATE DATABASE [{TEST_DB}]")
    admin.close()

    from app.core.config import get_settings
    from app.persistence.database import reset_engine_cache

    get_settings.cache_clear()
    reset_engine_cache()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    yield TEST_DB


@pytest.fixture()
def db(sql_database):
    """A SQLAlchemy session bound to the migrated test DB; data wiped after each test, reference data reseeded."""
    from sqlalchemy import text

    from app.core.config import set_campus_config
    from app.persistence.database import get_engine, get_sessionmaker
    from app.services.seed import seed_reference_data

    set_campus_config(CAMPUS)
    with get_sessionmaker()() as s:
        seed_reference_data(s, CAMPUS)
        s.commit()
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        with get_engine().begin() as conn:
            for table in DELETE_ORDER:
                conn.execute(text(f"DELETE FROM {table}"))
