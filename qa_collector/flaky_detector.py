"""Flag tests that alternate pass/fail across their last N runs on the same
branch. Run once per ingest cycle (see run.py); results feed the "flaky
test leaderboard" Grafana panel via the flaky_tests table -- that panel
reads this table directly rather than recomputing flip-detection in SQL on
every dashboard load.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg

DEFAULT_WINDOW = 10


def detect_flaky_tests(conn: psycopg.Connection, window: int = DEFAULT_WINDOW) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT repo_id, branch, suite, test_name
            FROM v_test_case_results
            WHERE status IN ('passed', 'failed')
            """
        )
        keys = cur.fetchall()

        flagged = 0
        for repo_id, branch, suite, test_name in keys:
            cur.execute(
                """
                SELECT status FROM v_test_case_results
                WHERE repo_id = %s AND branch = %s AND suite = %s AND test_name = %s
                  AND status IN ('passed', 'failed')
                ORDER BY run_started_at DESC
                LIMIT %s
                """,
                (repo_id, branch, suite, test_name, window),
            )
            statuses = [row[0] for row in cur.fetchall()]
            flips = sum(1 for a, b in zip(statuses, statuses[1:]) if a != b)
            is_flaky = flips > 0

            now = datetime.now(timezone.utc)
            cur.execute(
                """
                INSERT INTO flaky_tests
                    (repo_id, suite, test_name, branch, first_seen_at,
                     last_seen_at, flip_count, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (repo_id, suite, test_name, branch) DO UPDATE SET
                    last_seen_at = EXCLUDED.last_seen_at,
                    flip_count = EXCLUDED.flip_count,
                    is_active = EXCLUDED.is_active
                """,
                (repo_id, suite, test_name, branch, now, now, flips, is_flaky),
            )
            if is_flaky:
                flagged += 1
    conn.commit()
    return flagged
