"""Create (or recreate) a SQL Server database for local development / tests.

Usage: python scripts/dev_db.py [--drop] [--name findmything]
Reads TEST_ADMIN_DATABASE_URL (master connection) from backend/.env or the environment.
Local development only; never run against Azure.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pyodbc
from dotenv import dotenv_values


def admin_conn_str() -> str:
    env = dotenv_values(Path(__file__).resolve().parents[1] / "backend" / ".env")
    value = os.environ.get("TEST_ADMIN_DATABASE_URL") or env.get("TEST_ADMIN_DATABASE_URL")
    if not value:
        raise SystemExit("TEST_ADMIN_DATABASE_URL is not set (see backend/.env.example)")
    return value


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="findmything")
    ap.add_argument("--drop", action="store_true")
    args = ap.parse_args()
    if not args.name.replace("_", "").isalnum():
        raise SystemExit("Invalid database name")
    conn = pyodbc.connect(admin_conn_str(), autocommit=True)
    if args.drop:
        conn.execute(
            f"IF DB_ID('{args.name}') IS NOT NULL BEGIN "
            f"ALTER DATABASE [{args.name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{args.name}]; END"
        )
    conn.execute(f"IF DB_ID('{args.name}') IS NULL CREATE DATABASE [{args.name}]")
    print(f"database {args.name} ready")


if __name__ == "__main__":
    main()
