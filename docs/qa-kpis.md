# QA Automation KPI definitions

All of these are computed from `qa-postgres` (`qa_collector/schema.sql`), not DevLake — see `ARCHITECTURE.md` for why they live in a separate database. Dashboard: **QA Automation KPIs** (`grafana/dashboards/qa-automation-kpis.json`).

## Pass rate

`passed / (passed + failed)` over a time window, excluding `skipped` from the denominator (a skip is neither a pass nor a failure signal). Computed per repo and overall. Query pattern: `v_test_case_results` grouped by day/repo — see `dashboard-authoring` skill for the exact SQL.

## CI success rate

Distinct from pass rate: the fraction of `test_runs` rows whose `conclusion = 'success'`. A run can have a 100% test pass rate and still be `failure` at the run level (e.g. the lint/typecheck job failed before tests ran) — this metric catches that gap, pass rate alone doesn't.

## Flaky test

A test whose status alternates between `passed` and `failed` across its last 10 runs (`flaky_detector.DEFAULT_WINDOW`) on the same branch, with no other explanation tracked (this is intentionally a simple statistical definition, not a "known flaky, ignore" allowlist — a test that's *actually* just broken and someone keeps re-running until it passes will also trip this, which is arguably correct: it's still non-deterministic from the suite's point of view). `flip_count` is the number of pass/fail transitions in that window, used to rank the leaderboard panel — a test that flipped 6 times in its last 10 runs is a bigger problem than one that flipped once.

## Mean test duration

Average `duration_ms` per test-run-day, per repo. Tracked as a trend, not a single number, specifically to catch gradual test-suite slowdown (a common early signal of a suite that's about to become a CI bottleneck) rather than just a snapshot.

## Test tags

Playwright tests carry their `@smoke`/`@regression`/`@api`/etc. tag directly in the reported test title (`qa_collector/parsers/junit_parser.py` extracts it with a regex); pytest tests don't carry markers into JUnit XML by default, so their "tag" is inferred from the `tests/<marker>/` directory convention `backend-agentic` uses. k6 checks/thresholds get synthetic tags `k6-check`/`k6-threshold` (see `qa_collector/parsers/k6_parser.py`) so they show up in the same failures-by-tag panel as functional tests, distinguishable from them. A [CTRF](https://ctrf.io) report's own `tags` array is used as-is (`qa_collector/parsers/ctrf_parser.py`), plus a synthetic `ctrf-flaky` tag when the reporter set `flaky: true` on a test.

## Ingestion format

qa_collector accepts three input formats, auto-detected per artifact (see the `qa-metrics-ingest` skill for the exact dispatch rule): JUnit XML, a k6 `--summary-export` JSON file, or a [CTRF](https://ctrf.io) JSON report. CTRF is framework-agnostic (one parser covers Playwright/Jest/Mocha/Cypress/pytest/etc. reporters alike) and is the preferred format for onboarding a new repo — see `new-source-onboarding`.

## k6 performance metrics

Separate from the pass/fail check/threshold rows above: a k6 `--summary-export` file's top-level `metrics` object also carries k6's own built-in run-level aggregates -- latency percentiles, throughput, error rate, concurrency -- that don't fit a pass/fail shape at all. `qa_collector/parsers/k6_parser.py`'s `parse_k6_metrics` extracts the well-known ones (`http_req_duration`'s avg/p90/p95/p99/max, `http_reqs`/`iterations` count and rate, `http_req_failed`'s rate, `vus_max`, `data_sent`/`data_received`) into `qa-postgres`'s `k6_run_metrics` table, visualized on the **k6 Performance** dashboard (`grafana/dashboards/k6-performance.json`).

Two things worth knowing before touching this:

- **One aggregate row per (CI run, k6 script), trended build-over-build** — not a live, per-second view. A single k6 script run is reduced to one row of percentiles/rates, the same way `test_case_results.duration_ms` reduces a test to one number per run; the dashboard's line charts show how that number moves across CI runs over time. This answers "is checkout's p95 drifting worse over the last 30 builds", not "show me this run's live VU ramp" — that second question is a fundamentally different k6 output mode (`xk6-output-prometheus-remote` or InfluxDB streaming *while the load test runs*, paired with k6's own real-time Grafana dashboards), which this repo's "parse an artifact after CI finishes" architecture doesn't produce and isn't trying to.
- **Keyed on (test_run_id, source_file), not just test_run_id** — a single artifact/job can bundle multiple `--summary-export` files for genuinely different k6 scripts with different load profiles (confirmed against a real k6-agentic run: one `k6-summary` job's zip contained both a REST and a GraphQL summary file). The `k6-performance` dashboard's `$source_file` variable exists specifically to let a panel pick one script rather than silently averaging or overwriting between them.

Nullable throughout by design: k6's default `summaryTrendStats` only guarantees avg/min/med/max/p(90)/p(95) for a Trend metric, and `http_req_failed` itself was only added in k6 v0.31 — a NULL column means the run's k6 version/config didn't report that stat, not a collector bug.
