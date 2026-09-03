"""qa_collector CLI: pull recent GitHub Actions runs for one or all
configured repos, parse their JUnit/k6-summary artifacts, load them into
qa-postgres, then recompute the flaky-test leaderboard.

    python -m qa_collector.run                        # all repos, last 20 runs each
    python -m qa_collector.run --repo playwright-agentic --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys

from qa_collector import db, github_fetch
from qa_collector.flaky_detector import detect_flaky_tests
from qa_collector.normalize import TestRun, upsert_test_run
from qa_collector.parsers.junit_parser import parse_junit_xml
from qa_collector.parsers.k6_parser import parse_k6_summary

REPOS = {
    "playwright-agentic": {"org": "autom8ion", "framework": "playwright"},
    "backend-agentic": {"org": "autom8ion", "framework": "pytest"},
    "k6-agentic": {"org": "autom8ion", "framework": "k6"},
}


def _cases_for_artifact(artifact_key: str, raw: bytes, workflow_name: str) -> list:
    if artifact_key.endswith(".xml"):
        return parse_junit_xml(raw)
    if artifact_key.endswith(".json"):
        summary = json.loads(raw)
        return parse_k6_summary(summary, suite=workflow_name)
    return []


def ingest_repo(conn, repo_id: str, limit: int) -> int:
    cfg = REPOS[repo_id]
    ingested = 0
    for run in github_fetch.list_recent_runs(cfg["org"], repo_id, per_page=limit):
        files = github_fetch.fetch_artifact_files(cfg["org"], repo_id, run.run_id)
        if not files:
            continue

        # Group files by artifact name (junit-results / k6-summary /
        # k6-db-summary) -- each artifact group becomes one test_runs row,
        # using the artifact name as job_name so e.g. k6's rest+graphql+db
        # smoke jobs show up as separate rows under the same workflow run.
        by_artifact: dict[str, list[tuple[str, bytes]]] = {}
        for key, raw in files.items():
            artifact_name = key.split("/", 1)[0]
            by_artifact.setdefault(artifact_name, []).append((key, raw))

        for artifact_name, members in by_artifact.items():
            cases = []
            for key, raw in members:
                cases.extend(_cases_for_artifact(key, raw, run.workflow_name))
            if not cases:
                continue

            test_run = TestRun(
                repo_id=repo_id,
                workflow_run_id=run.run_id,
                workflow_name=run.workflow_name,
                job_name=artifact_name,
                branch=run.branch,
                commit_sha=run.commit_sha,
                triggered_by=run.event,
                started_at=run.started_at,
                finished_at=run.finished_at,
                conclusion=run.conclusion,
                source="k6-summary" if artifact_name.startswith("k6") else "junit",
                cases=cases,
            )
            upsert_test_run(conn, test_run)
            ingested += 1
    return ingested


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", choices=sorted(REPOS), help="Ingest only this repo (default: all)")
    parser.add_argument("--limit", type=int, default=20, help="Recent completed workflow runs to check per repo")
    args = parser.parse_args()

    conn = db.connect()
    db.ensure_schema(conn)

    repos = [args.repo] if args.repo else list(REPOS)
    total = 0
    for repo_id in repos:
        count = ingest_repo(conn, repo_id, args.limit)
        print(f"{repo_id}: ingested {count} run/job result set(s)")
        total += count

    flagged = detect_flaky_tests(conn)
    print(f"flaky-test detector: {flagged} test(s) currently flagged flaky")
    print(f"total ingested: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
