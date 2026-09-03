# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What this is

A QA Automation KPI Dashboard example: Apache DevLake + Grafana OSS for engineering/DORA analytics, plus a small custom pipeline (`qa_collector`) that fills the one gap DevLake doesn't cover -- test-case-level results (pass/fail/flaky/duration) from GitHub Actions. See `ARCHITECTURE.md` for the full design and *why* each piece exists, `README.md` for the `make demo` quickstart.

## Non-negotiables

1. **DevLake's own MySQL schema is never touched directly.** All custom test-result data lives in `qa-postgres`, owned entirely by `qa_collector/schema.sql`. See `ARCHITECTURE.md` "Why a separate qa-postgres" -- this is deliberate, not an oversight.
2. **Dashboards and datasources are provisioned as code**, never hand-edited in the Grafana UI. Edit `grafana/dashboards/*.json` / `grafana/provisioning/`; provisioning reloads automatically. See `dashboard-authoring` skill.
3. **`qa_collector` writes are idempotent.** Every insert path goes through `ON CONFLICT DO UPDATE`/`upsert_test_run` -- re-ingesting the same GitHub Actions run must never duplicate rows. Preserve this on any change to `qa_collector/normalize.py`.
4. **DevLake connections/scopes are configured via its REST API** (`devlake/scripts/bootstrap.sh`), not manual UI clicking -- except the Project/Blueprint creation step, which is deliberately left to the Config UI wizard (see that script's header comment for why). Don't "finish the job" by hand-crafting a blueprint API payload without re-reading that rationale first.
5. **Claude-generated reports are judgment, not a data dump.** The `qa-kpi-report` skill exists because turning several simultaneous numeric trends into "here's what actually matters" is genuinely a task an LLM adds value on; don't let it regress into restating dashboard panels in prose.

## Commands

```bash
cp .env.example .env         # then edit: GITHUB_TOKEN for live data, or leave blank for seeded-only
make demo                    # up + bootstrap DevLake + seed sample data, prints URLs
make ingest                  # pull real GitHub Actions test results into qa-postgres (needs GITHUB_TOKEN)
make report                  # run the qa-kpi-report skill headlessly, writes reports/<date>.md
make down / make clean       # tear down (clean also removes the local venv)
```

## Directory map

```
qa_collector/        The DevLake gap-filler: fetch GitHub Actions artifacts, parse, normalize, load, flag flaky tests
  schema.sql          Owned schema for qa-postgres -- the source of truth, read it before writing a query against it
  github_fetch.py      Lists workflow runs, downloads JUnit/k6-summary/CTRF artifacts
  parsers/             junit_parser.py (Playwright + pytest), k6_parser.py, ctrf_parser.py (framework-agnostic)
  normalize.py          Shared TestRun/TestCase shape + the one upsert write path
  flaky_detector.py     Pass/fail-alternation flakiness detection
  run.py                CLI entrypoint (python -m qa_collector.run)
devlake/scripts/      bootstrap.sh -- config-as-code for DevLake connections/scopes/scope-config
scripts/seed/          generate_sample_data.py -- synthetic 30-day history for a zero-credential demo
grafana/               provisioning/ (datasources, dashboard provider) + dashboards/*.json
docs/                  dora-metrics.md, qa-kpis.md -- metric definitions and source mapping
.github/workflows/     collect-qa-metrics.yml, qa-kpi-report.yml -- the always-on / real-deployment path
.claude/skills/        devlake-bootstrap, qa-metrics-ingest, dashboard-authoring, qa-kpi-report, new-source-onboarding
reports/               Committed Markdown output of the qa-kpi-report skill
```

## Skills index

- `.claude/skills/devlake-bootstrap/SKILL.md` -- configure/troubleshoot DevLake connections, scopes, DORA scope-config
- `.claude/skills/qa-metrics-ingest/SKILL.md` -- run/debug qa_collector, add a new test-result-format parser
- `.claude/skills/dashboard-authoring/SKILL.md` -- add/edit a Grafana panel or dashboard as code
- `.claude/skills/qa-kpi-report/SKILL.md` -- generate the narrative QA KPI report
- `.claude/skills/new-source-onboarding/SKILL.md` -- router for adding a 4th+ repo as a data source

## Known limitation, by design

`playwright-agentic`/`k6-agentic`/`backend-agentic` are QA test-framework repos, not deployable applications -- none of their CI jobs represent a real production deploy. Live GitHub-sourced DORA deployment/change-failure signal is therefore near-zero for them; the demo's DORA panels are populated from `scripts/seed/generate_sample_data.py`'s synthetic deployments/incidents instead. Point `devlake/scripts/bootstrap.sh`'s `DEPLOYMENT_PATTERN`/`PRODUCTION_PATTERN` at a real application repo to get live DORA signal for real. See `docs/dora-metrics.md`.
