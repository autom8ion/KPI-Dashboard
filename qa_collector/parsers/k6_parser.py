"""Parse a k6 `--summary-export` JSON file into qa_collector's normalized
shapes: a TestCase list (checks/thresholds, pass-rate panels) and a
K6Metrics (the run's performance aggregates -- latency, throughput, error
rate, concurrency -- that don't fit the pass/fail shape at all).

k6 has no concept of a "test case" -- it has per-request `checks` (grouped
under `root_group`, recursively, for sub-groups) and per-metric
`thresholds`. We turn each into a synthetic TestCase: one per check (suite =
the k6 script file, test_name = the check's path) and one per threshold
(test_name = "threshold: <expression>"). This shape has moved between k6
versions before; if `k6-agentic`'s pinned k6 version changes its
--summary-export schema, this is the file to update (see the
k6-framework-maintenance skill in k6-agentic for version-audit habits).

Separately, the same summary JSON's top-level `metrics` object carries
k6's own built-in aggregates (`http_req_duration`, `http_reqs`,
`http_req_failed`, `vus_max`, `iterations`, `data_sent`/`data_received`).
`parse_k6_metrics` pulls the well-known ones into K6Metrics -- see that
dataclass and schema.sql's k6_run_metrics for why most fields are nullable
(not every k6 version/config reports every stat).
"""

from __future__ import annotations

from qa_collector.normalize import K6Metrics, TestCase


def _children(container: dict | list | None) -> list:
    """A group's `checks`/`groups` has been observed as both a dict keyed by
    check/group name (current k6-agentic pinned version -- confirmed against
    a real --summary-export) and a bare list (older k6 versions, per this
    module's original assumption). Normalize both to a list of values so a
    real run doesn't crash a collector that was only ever exercised against
    guessed/seeded shapes."""
    if isinstance(container, dict):
        return list(container.values())
    return list(container or [])


def _walk_checks(group: dict, cases: list[TestCase], suite: str) -> None:
    for check in _children(group.get("checks")):
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
    for sub_group in _children(group.get("groups")):
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


def _num(metric: dict, *keys: str) -> float | None:
    """First present numeric value among `keys` in one metrics[...] entry,
    or None if the metric/key is missing (see K6Metrics for why that's
    expected, not an error)."""
    for key in keys:
        if key in metric and metric[key] is not None:
            return metric[key]
    return None


def parse_k6_metrics(summary_json: dict) -> K6Metrics | None:
    """Extract run-level performance aggregates from a k6 `--summary-export`
    JSON's `metrics` object. Returns None if the file has no `metrics` key
    at all (e.g. a hand-crafted/malformed export) -- an empty K6Metrics
    would otherwise look like "a k6 run with zero traffic", which is a
    different, misleading claim."""
    metrics = summary_json.get("metrics")
    if not metrics:
        return None

    http_req_duration = metrics.get("http_req_duration", {})
    # k6 renamed vus_max's shape across versions; vus.max is the fallback
    # for older exports that only report the live `vus` gauge.
    vus = metrics.get("vus_max") or metrics.get("vus") or {}
    http_reqs = metrics.get("http_reqs", {})
    http_req_failed = metrics.get("http_req_failed", {})  # added in k6 v0.31
    iterations = metrics.get("iterations", {})
    data_received = metrics.get("data_received", {})
    data_sent = metrics.get("data_sent", {})

    def _int(v: float | None) -> int | None:
        return round(v) if v is not None else None

    return K6Metrics(
        vus_max=_int(_num(vus, "value", "max")),
        http_reqs_count=_int(_num(http_reqs, "count")),
        http_reqs_rate=_num(http_reqs, "rate"),
        http_req_failed_rate=_num(http_req_failed, "value", "rate"),
        http_req_duration_avg_ms=_num(http_req_duration, "avg"),
        http_req_duration_p90_ms=_num(http_req_duration, "p(90)"),
        http_req_duration_p95_ms=_num(http_req_duration, "p(95)"),
        http_req_duration_p99_ms=_num(http_req_duration, "p(99)"),
        http_req_duration_max_ms=_num(http_req_duration, "max"),
        iterations_count=_int(_num(iterations, "count")),
        iterations_rate=_num(iterations, "rate"),
        data_received_bytes=_int(_num(data_received, "count")),
        data_sent_bytes=_int(_num(data_sent, "count")),
    )
