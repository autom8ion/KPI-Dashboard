"""Generate ~30 days of synthetic QA + DORA history so `make demo` shows a
fully populated dashboard with zero live credentials.

Writes to two places:
  - qa-postgres (via qa_collector.normalize) -- test runs/cases for all
    three sibling repos, with a couple of deliberately flaky tests and one
    visible regression.
  - DevLake, via its webhook plugin (verified against v1.0.3-beta16's
    backend/plugins/webhook/api/*.go) -- synthetic deployments and
    Jira-shaped issues (bugs/incidents), so the DORA Overview dashboard has
    numbers even without a real Jira connection or an actual deployable
    application repo (playwright-agentic/k6-agentic/backend-agentic are QA
    test frameworks, not applications with real production deploys -- see
    devlake/scripts/bootstrap.sh's DEPLOYMENT_PATTERN comment).

Idempotent: a fixed random seed and fixed synthetic ids mean re-running
regenerates and upserts the same window rather than duplicating rows.
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

import requests

from qa_collector import db
from qa_collector.normalize import TestCase, TestRun, upsert_test_run

RNG = random.Random(20260101)
DAYS = 30
DEVLAKE_API_URL = os.environ.get("DEVLAKE_API_URL", "http://localhost:8080")
WEBHOOK_CONN_NAME = "qa-automation-seed"

REPO_SUITES = {
    "playwright-agentic": {
        "tests/app/functional/login.spec.ts": [
            "test logs in with valid credentials @smoke",
            "test rejects invalid password @smoke",
        ],
        "tests/app/functional/bookstore.spec.ts": [
            "test searches for a book @regression",
            "test adds a book to collection @regression",
        ],
        "tests/app/api/books.api.spec.ts": ["test lists books @api", "test creates a book @api"],
    },
    "backend-agentic": {
        "tests/rest/test_orders_rest.py": ["test_create_order", "test_get_order"],
        "tests/graphql/test_orders_graphql.py": ["test_query_order"],
        "tests/db/test_orders_db.py": ["test_created_order_is_persisted"],
        "tests/e2e/test_order_lifecycle.py": ["test_full_order_lifecycle"],
    },
    "k6-agentic": {
        "tests/rest/smoke.ts": ["threshold: http_req_duration p(95)<500", "status is 200"],
        "tests/graphql/smoke.ts": ["threshold: http_req_duration p(95)<800", "no errors in response"],
    },
}

# Deliberately flaky: alternates pass/fail across the seeded window, so the
# "flaky test leaderboard" panel has something to show on first run.
FLAKY = {
    ("playwright-agentic", "tests/app/functional/bookstore.spec.ts", "test searches for a book @regression"),
    ("backend-agentic", "tests/e2e/test_order_lifecycle.py", "test_full_order_lifecycle"),
}

# A visible regression: this test starts failing from REGRESSION_DAY onward,
# so the pass-rate trend panel has a believable step-down to show.
REGRESSION = ("backend-agentic", "tests/graphql/test_orders_graphql.py", "test_query_order")
REGRESSION_DAY = 24


def _status_for(repo: str, suite: str, name: str, day_index: int) -> str:
    key = (repo, suite, name)
    if key == REGRESSION and day_index >= REGRESSION_DAY:
        return "failed"
    if key in FLAKY:
        return "failed" if day_index % 3 == 1 else "passed"
    return "failed" if RNG.random() < 0.03 else "passed"


def seed_qa_postgres() -> None:
    conn = db.connect()
    db.ensure_schema(conn)

    now = datetime.now(timezone.utc)
    workflow_run_id = 900_000_000  # synthetic id space, clear of real GitHub run ids

    for day_index in range(DAYS):
        run_time = now - timedelta(days=DAYS - day_index)
        for repo_id, suites in REPO_SUITES.items():
            cases: list[TestCase] = []
            for suite, names in suites.items():
                for name in names:
                    status = _status_for(repo_id, suite, name, day_index)
                    cases.append(
                        TestCase(
                            suite=suite,
                            test_name=name,
                            status=status,
                            tags=["seed"],
                            duration_ms=RNG.randint(80, 2500),
                            error_message="Seeded synthetic failure" if status == "failed" else None,
                        )
                    )
            workflow_run_id += 1
            run = TestRun(
                repo_id=repo_id,
                workflow_run_id=workflow_run_id,
                workflow_name="CI",
                job_name="seed",
                branch="main",
                commit_sha=f"seed{workflow_run_id:x}",
                triggered_by="seed",
                started_at=run_time,
                finished_at=run_time + timedelta(minutes=RNG.randint(2, 12)),
                conclusion="failure" if any(c.status == "failed" for c in cases) else "success",
                source="seed",
                cases=cases,
            )
            upsert_test_run(conn, run)
    print(f"qa-postgres: seeded {DAYS} days x {len(REPO_SUITES)} repos")


def _ensure_webhook_connection(session: requests.Session) -> bool:
    resp = session.get(f"{DEVLAKE_API_URL}/plugins/webhook/connections", timeout=15)
    if resp.ok and any(c.get("name") == WEBHOOK_CONN_NAME for c in resp.json()):
        return True
    resp = session.post(
        f"{DEVLAKE_API_URL}/plugins/webhook/connections",
        json={"name": WEBHOOK_CONN_NAME},
        timeout=15,
    )
    return resp.ok


def seed_devlake_dora() -> None:
    session = requests.Session()
    try:
        if not _ensure_webhook_connection(session):
            print("DevLake webhook connection setup failed -- skipping DORA seed (qa-postgres seed still applied).")
            return
    except requests.RequestException:
        print("DevLake not reachable -- skipping DORA seed (qa-postgres seed still applied). Try `make seed` again.")
        return

    now = datetime.now(timezone.utc)

    for day_index in range(DAYS):
        deploy_time = now - timedelta(days=DAYS - day_index, hours=RNG.randint(0, 8))
        finished = deploy_time + timedelta(minutes=RNG.randint(3, 20))
        failed = RNG.random() < 0.08
        session.post(
            f"{DEVLAKE_API_URL}/plugins/webhook/connections/by-name/{WEBHOOK_CONN_NAME}/deployments",
            json={
                "id": f"seed-deploy-{day_index}",
                "displayTitle": f"Deploy #{day_index}",
                "result": "FAILURE" if failed else "SUCCESS",
                "environment": "PRODUCTION",
                "startedDate": deploy_time.isoformat(),
                "finishedDate": finished.isoformat(),
                "deploymentCommits": [
                    {
                        "repoUrl": "https://github.com/autom8ion/backend-agentic",
                        "commitSha": f"{RNG.getrandbits(160):040x}",
                        "refName": "refs/heads/main",
                        "result": "FAILURE" if failed else "SUCCESS",
                        "startedDate": deploy_time.isoformat(),
                        "finishedDate": finished.isoformat(),
                    }
                ],
            },
            timeout=15,
        )

    bugs = [
        ("SEED-BUG-1", "Flaky bookstore search under load", now - timedelta(days=18), now - timedelta(days=15)),
        ("SEED-BUG-2", "GraphQL order query regression", now - timedelta(days=6), None),
    ]
    for key, title, created, resolved in bugs:
        session.post(
            f"{DEVLAKE_API_URL}/plugins/webhook/connections/by-name/{WEBHOOK_CONN_NAME}/issues",
            json={
                "issueKey": key,
                "title": title,
                "type": "BUG",
                "status": "DONE" if resolved else "IN_PROGRESS",
                "originalStatus": "Done" if resolved else "In Progress",
                "createdDate": created.isoformat(),
                "resolutionDate": resolved.isoformat() if resolved else None,
                "severity": "Medium",
            },
            timeout=15,
        )

    incident_created = now - timedelta(days=10)
    incident_resolved = incident_created + timedelta(hours=3, minutes=45)
    session.post(
        f"{DEVLAKE_API_URL}/plugins/webhook/connections/by-name/{WEBHOOK_CONN_NAME}/issues",
        json={
            "issueKey": "SEED-INC-1",
            "title": "Production checkout latency spike",
            "type": "INCIDENT",
            "status": "DONE",
            "originalStatus": "Resolved",
            "createdDate": incident_created.isoformat(),
            "resolutionDate": incident_resolved.isoformat(),
            "severity": "High",
        },
        timeout=15,
    )

    print(f"DevLake: seeded {DAYS} synthetic deployments, {len(bugs)} bugs, 1 incident via the webhook plugin")


def main() -> None:
    seed_qa_postgres()
    seed_devlake_dora()


if __name__ == "__main__":
    main()
