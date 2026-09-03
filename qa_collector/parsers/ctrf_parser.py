"""Parse a CTRF (Common Test Report Format, https://ctrf.io) report into
qa_collector's normalized TestCase list.

CTRF is a framework-agnostic JSON schema with reporters for most major test
tools (Playwright, Jest, Mocha, Cypress, pytest via pytest-ctrf-json, ...) --
one parser here covers any of them, unlike junit_parser.py which needs a
per-framework tag-extraction heuristic. Schema reference (verified against
https://ctrf.io/docs/specification/overview):

    {"results": {"tool": {...}, "summary": {...}, "tests": [
        {"name": ..., "status": ..., "duration": ...,       # required
         "suite": ..., "filePath": ..., "message": ..., "trace": ...,
         "tags": [...], "flaky": bool, "retries": int, ...}  # optional
    ]}}

`status` is one of passed/failed/pending/skipped; pending is folded into
skipped since qa-postgres only tracks those three states.
"""

from __future__ import annotations

from qa_collector.normalize import TestCase

_STATUS_MAP = {
    "passed": "passed",
    "failed": "failed",
    "skipped": "skipped",
    "pending": "skipped",
}


def is_ctrf_report(data: object) -> bool:
    """Cheap content sniff so callers can tell a CTRF report apart from
    other JSON artifacts (e.g. a k6 --summary-export file) without relying
    on the artifact's filename."""
    return isinstance(data, dict) and isinstance(data.get("results", {}).get("tests"), list)


def parse_ctrf(report: dict, default_suite: str = "unknown-suite") -> list[TestCase]:
    tests = report.get("results", {}).get("tests", [])
    cases: list[TestCase] = []
    for t in tests:
        status = _STATUS_MAP.get(t.get("status", ""), "skipped")
        tags = list(t.get("tags") or [])
        if t.get("flaky"):
            # CTRF reporters set this when a retry within the same CI run
            # changed status -- a stronger, tool-reported signal than our
            # own statistical flaky_detector.py. Surfaced as a tag rather
            # than a schema change so it flows through the same
            # pass-rate/tag-breakdown panels as everything else, and shows
            # up in flaky_detector's own history-based detection too once
            # enough runs accumulate.
            tags.append("ctrf-flaky")

        message = t.get("message") or t.get("trace")
        cases.append(
            TestCase(
                suite=t.get("suite") or t.get("filePath") or default_suite,
                test_name=t.get("name", "unknown-test"),
                status=status,
                tags=tags,
                duration_ms=t.get("duration"),
                error_message=(str(message)[:4000] if message and status == "failed" else None),
            )
        )
    return cases
