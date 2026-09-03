"""qa-postgres connection helper. See schema.sql for the owned schema."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect() -> psycopg.Connection:
    dsn = os.environ.get(
        "QA_POSTGRES_DSN",
        "postgresql://qa:qa@localhost:5433/qa_metrics",
    )
    return psycopg.connect(dsn)


def ensure_schema(conn: psycopg.Connection) -> None:
    """Apply schema.sql. Safe to call on every run -- every statement in it
    is CREATE TABLE/INDEX/VIEW IF NOT EXISTS or ON CONFLICT DO NOTHING."""
    conn.execute(_SCHEMA_PATH.read_text())
    conn.commit()
