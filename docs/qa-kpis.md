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

Playwright tests carry their `@smoke`/`@regression`/`@api`/etc. tag directly in the reported test title (`qa_collector/parsers/junit_parser.py` extracts it with a regex); pytest tests don't carry markers into JUnit XML by default, so their "tag" is inferred from the `tests/<marker>/` directory convention `backend-agentic` uses. k6 checks/thresholds get synthetic tags `k6-check`/`k6-threshold` (see `qa_collector/parsers/k6_parser.py`) so they show up in the same failures-by-tag panel as functional tests, distinguishable from them.
