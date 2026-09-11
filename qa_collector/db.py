"""qa-postgres connection helper. See schema.sql for the owned schema."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

from qa_collector.config import load as load_sources_config

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect() -> psycopg.Connection:
    dsn = os.environ.get(
        "QA_POSTGRES_DSN",
        "postgresql://qa:qa@localhost:5433/qa_metrics",
    )
    return psycopg.connect(dsn)


def ensure_schema(conn: psycopg.Connection) -> None:
    """Apply schema.sql, then sync the `repos` table from config/sources.yaml.
    Safe to call on every run -- schema.sql is all CREATE ... IF NOT EXISTS,
    and the repos sync is an upsert keyed on id."""
    conn.execute(_SCHEMA_PATH.read_text())
    conn.commit()
    _sync_repos(conn)


def _sync_repos(conn: psycopg.Connection) -> None:
    for repo_id, info in load_sources_config().qa_collector_repos().items():
        conn.execute(
            """
            INSERT INTO repos (id, github_org, github_repo, framework)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                github_org = EXCLUDED.github_org,
                github_repo = EXCLUDED.github_repo,
                framework = EXCLUDED.framework
            """,
            (repo_id, info["org"], repo_id, info["framework"]),
        )
    conn.commit()
