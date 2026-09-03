"""GitHub Actions polling: list recently completed workflow runs for a repo
and download the JUnit XML / k6 summary / CTRF artifacts they published.

Artifact names match the sibling-repo CI changes made alongside this
collector: `junit-results` (playwright-agentic, backend-agentic),
`k6-summary` and `k6-db-summary` (k6-agentic). `ctrf-report` is also
recognized for any repo that publishes a CTRF (https://ctrf.io) JSON report
instead of/in addition to JUnit XML -- see qa_collector/parsers/ctrf_parser.py.
"""

from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime

import requests

GITHUB_API = "https://api.github.com"

KNOWN_ARTIFACT_NAMES = {"junit-results", "k6-summary", "k6-db-summary", "ctrf-report"}


@dataclass
class WorkflowRun:
    run_id: int
    workflow_name: str
    branch: str
    commit_sha: str
    event: str
    started_at: datetime
    finished_at: datetime | None
    conclusion: str | None


def _session() -> requests.Session:
    s = requests.Session()
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    s.headers["Accept"] = "application/vnd.github+json"
    s.headers["X-GitHub-Api-Version"] = "2022-11-28"
    return s


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def list_recent_runs(org: str, repo: str, per_page: int = 20) -> list[WorkflowRun]:
    session = _session()
    resp = session.get(
        f"{GITHUB_API}/repos/{org}/{repo}/actions/runs",
        params={"status": "completed", "per_page": per_page},
        timeout=30,
    )
    resp.raise_for_status()
    runs = []
    for r in resp.json().get("workflow_runs", []):
        started = _parse_dt(r.get("run_started_at")) or _parse_dt(r["created_at"])
        runs.append(
            WorkflowRun(
                run_id=r["id"],
                workflow_name=r["name"],
                branch=r["head_branch"] or "unknown",
                commit_sha=r["head_sha"],
                event=r["event"],
                started_at=started,
                finished_at=_parse_dt(r.get("updated_at")),
                conclusion=r.get("conclusion"),
            )
        )
    return runs


def fetch_artifact_files(org: str, repo: str, run_id: int) -> dict[str, bytes]:
    """Returns {"<artifact-name>/<file-in-zip>": raw bytes} for every
    known JUnit/k6-summary artifact attached to one workflow run."""
    session = _session()
    resp = session.get(
        f"{GITHUB_API}/repos/{org}/{repo}/actions/runs/{run_id}/artifacts",
        timeout=30,
    )
    resp.raise_for_status()
    files: dict[str, bytes] = {}
    for artifact in resp.json().get("artifacts", []):
        name = artifact["name"]
        if name not in KNOWN_ARTIFACT_NAMES:
            continue
        dl = session.get(artifact["archive_download_url"], timeout=60)
        dl.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(dl.content)) as zf:
            for member in zf.namelist():
                if member.endswith(".xml") or member.endswith(".json"):
                    files[f"{name}/{member}"] = zf.read(member)
    return files
