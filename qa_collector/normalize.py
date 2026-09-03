"""Shared normalized shape every parser (JUnit, k6 summary) produces.

Every source format -- Playwright's junit reporter, pytest's --junitxml,
k6's --summary-export JSON -- gets turned into these two dataclasses before
touching the database. Parsers never write SQL directly; `upsert_test_run`
is the single write path, so schema.sql's UNIQUE constraints (not
duplicated application logic) are what makes re-ingesting the same GitHub
Actions run idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import psycopg


@dataclass
class TestCase:
    suite: str
    test_name: str
    status: str  # passed | failed | skipped
    tags: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    error_message: str | None = None


@dataclass
class TestRun:
    repo_id: str
    workflow_run_id: int
    workflow_name: str
    branch: str
    commit_sha: str
    started_at: datetime
    source: str  # junit | k6-summary | seed
    job_name: str = ""
    finished_at: datetime | None = None
    conclusion: str | None = None
    triggered_by: str | None = None
    cases: list[TestCase] = field(default_factory=list)


def upsert_test_run(conn: psycopg.Connection, run: TestRun) -> int:
    """Insert or replace one test_runs row and all of its test_case_results.

    Idempotent by design: re-ingesting the same (repo_id, workflow_run_id,
    job_name) -- e.g. because the collector's polling window overlaps the
    previous run -- deletes and replaces that run's test_case_results
    (via ON DELETE CASCADE from a fresh id) rather than growing duplicate
    rows.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO test_runs
                (repo_id, workflow_run_id, workflow_name, job_name, branch,
                 commit_sha, triggered_by, started_at, finished_at,
                 conclusion, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (repo_id, workflow_run_id, job_name) DO UPDATE SET
                workflow_name = EXCLUDED.workflow_name,
                branch = EXCLUDED.branch,
                commit_sha = EXCLUDED.commit_sha,
                triggered_by = EXCLUDED.triggered_by,
                started_at = EXCLUDED.started_at,
                finished_at = EXCLUDED.finished_at,
                conclusion = EXCLUDED.conclusion,
                source = EXCLUDED.source,
                ingested_at = now()
            RETURNING id
            """,
            (
                run.repo_id,
                run.workflow_run_id,
                run.workflow_name,
                run.job_name,
                run.branch,
                run.commit_sha,
                run.triggered_by,
                run.started_at,
                run.finished_at,
                run.conclusion,
                run.source,
            ),
        )
        row = cur.fetchone()
        assert row is not None
        test_run_id = row[0]

        # Re-ingesting a run replaces its test case rows outright -- simpler
        # and safer than reconciling adds/removes/renames case by case.
        cur.execute("DELETE FROM test_case_results WHERE test_run_id = %s", (test_run_id,))
        for case in run.cases:
            cur.execute(
                """
                INSERT INTO test_case_results
                    (test_run_id, suite, test_name, tags, status,
                     duration_ms, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (test_run_id, suite, test_name) DO UPDATE SET
                    tags = EXCLUDED.tags,
                    status = EXCLUDED.status,
                    duration_ms = EXCLUDED.duration_ms,
                    error_message = EXCLUDED.error_message
                """,
                (
                    test_run_id,
                    case.suite,
                    case.test_name,
                    case.tags,
                    case.status,
                    case.duration_ms,
                    case.error_message,
                ),
            )
    conn.commit()
    return test_run_id
