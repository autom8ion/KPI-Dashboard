"""Parse a k6 `--summary-export` JSON file into qa_collector's normalized
TestCase list, so k6 checks/thresholds land in the same pass-rate panels as
Playwright/pytest tests.

k6 has no concept of a "test case" -- it has per-request `checks` (grouped
under `root_group`, recursively, for sub-groups) and per-metric
`thresholds`. We turn each into a synthetic TestCase: one per check (suite =
the k6 script file, test_name = the check's path) and one per threshold
(test_name = "threshold: <expression>"). This shape has moved between k6
versions before; if `k6-agentic`'s pinned k6 version changes its
--summary-export schema, this is the file to update (see the
k6-framework-maintenance skill in k6-agentic for version-audit habits).
"""

from __future__ import annotations

from qa_collector.normalize import TestCase


def _walk_checks(group: dict, cases: list[TestCase], suite: str) -> None:
    for check in group.get("checks", []):
        passes = check.get("passes", 0)
        fails = check.get("fails", 0)
        status = "failed" if fails > 0 else ("skipped" if passes == 0 else "passed")
        cases.append(
            TestCase(
                suite=suite,
                test_name=check.get("path") or check.get("name", "unknown-check"),
                status=status,
                tags=["k6-check"],
                error_message=(f"{fails}/{fails + passes} iterations failed" if fails else None),
            )
        )
    for sub_group in group.get("groups", []):
        _walk_checks(sub_group, cases, suite)


def parse_k6_summary(summary_json: dict, suite: str) -> list[TestCase]:
    cases: list[TestCase] = []

    root_group = summary_json.get("root_group")
    if root_group:
        _walk_checks(root_group, cases, suite)

    thresholds = summary_json.get("thresholds", {})
    if not thresholds:
        # Older/alternate export shape: thresholds nested under each metric.
        for metric_name, metric in summary_json.get("metrics", {}).items():
            for expr, result in (metric.get("thresholds") or {}).items():
                thresholds[f"{metric_name}: {expr}"] = result

    for expr, result in thresholds.items():
        ok = result.get("ok", True) if isinstance(result, dict) else bool(result)
        cases.append(
            TestCase(
                suite=suite,
                test_name=f"threshold: {expr}",
                status="passed" if ok else "failed",
                tags=["k6-threshold"],
            )
        )

    return cases
