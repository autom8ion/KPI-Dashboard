# KPI-Dashboard

QA Automation KPI Dashboard -- a fully worked example of Apache DevLake + Grafana OSS for engineering/DORA analytics, extended with a small custom pipeline for test-level QA KPIs (pass rate, flaky tests, CI health) that DevLake doesn't natively ingest. Ships demoed against three sibling repos in this org (`playwright-agentic`, `k6-agentic`, `backend-agentic`) with synthetic data and zero credentials, and is config-driven -- see "Plugging in your own repos" below to point the whole stack at a different org/SDLC by editing one file.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full design and the reasoning behind each piece.

## Quickstart

```bash
git clone https://github.com/autom8ion/KPI-Dashboard.git && cd KPI-Dashboard
cp .env.example .env       # optionally add GITHUB_TOKEN for live data; blank = seeded demo
make demo                  # docker compose up, configure DevLake, seed ~30 days of sample data
```

Then open:

- **Grafana** — http://localhost:4000/grafana (`admin`/`admin` on first login) — see the **QA Automation** folder for the new dashboard this repo adds, and DevLake's own **General** folder (DORA, Github, Jira, Homepage — provisioned automatically by DevLake's Grafana image, no setup needed) for engineering analytics.
- **DevLake Config UI** — http://localhost:4000 — connections, projects, blueprints.

`make demo` seeds everything so the dashboards are populated immediately. To pull *real* GitHub Actions results instead: put a token in `.env` and run `make ingest`. See `make help`-equivalent targets in the [`Makefile`](Makefile): `up`, `down`, `bootstrap`, `seed`, `ingest`, `report`, `clean`.

## Plugging in your own repos

Everything org/repo-specific lives in one file: [`config/sources.yaml`](config/sources.yaml). To point this whole stack -- `qa_collector`'s ingestion, `devlake/scripts/bootstrap.sh`'s GitHub connection/scopes, and the demo seed data -- at a different SDLC:

1. Edit `config/sources.yaml`: set `github_org`, and list each repo you want tracked. Give a repo a `framework: playwright | pytest | k6` if you want `qa_collector` to ingest its JUnit/k6-summary/CTRF test results; omit `framework` for a repo you only want DevLake's DORA/PR/issue signal from (see `qa_collector/config.py`'s docstring for the exact shape).
2. If any of those repos publish a test-result artifact in a format `qa_collector` doesn't parse yet, see the `qa-metrics-ingest` skill's "Adding a new test-result format" section.
3. Put a GitHub PAT with read access to those repos in `.env` (`GITHUB_TOKEN`), and run `make demo` (or `make bootstrap && make ingest` if the stack is already up).

No other file needs editing -- `make bootstrap`/`make seed`/`make ingest` all read the same config. See the `new-source-onboarding` skill for the full checklist (CI export format, Grafana panels, verification steps).

## Screenshots

**QA Automation KPIs** — this repo's own dashboard: pass rate, CI success rate, flaky tests, per-repo trends, recent failures. A `$repo` filter scopes every panel, and summary panels (per-repo bars/trend lines, failure tags) link into filtered/detail views -- clicking a repo or tag re-filters the dashboard, and clicking a test name drills into **QA Test Case History** (`grafana/dashboards/qa-test-case-history.json`), which has its own run-by-run timeline plus direct links out to the GitHub Actions run and commit.

![QA Automation KPIs dashboard](docs/screenshots/qa-automation-kpis-dashboard.jpg)

**DORA** — DevLake's own dashboard, computed from the same seeded deployments/incidents.

![DORA dashboard](docs/screenshots/dora-dashboard.jpg)

## What's real vs. seeded

| Data | Source | Needs |
|---|---|---|
| GitHub PRs, commits, issues, CI pipeline runs | DevLake's GitHub plugin | `GITHUB_TOKEN` in `.env` |
| Test-case pass/fail/duration/flaky | `qa_collector` (this repo, JUnit/k6-summary/CTRF artifacts) | `GITHUB_TOKEN`, plus the sibling repos' CI changes (already applied — see their `feat/qa-kpi-dashboard-integration` branches) |
| DORA deployments/incidents/bugs | Seeded via DevLake's webhook plugin | nothing — synthetic by default |
| Jira issues | Seeded (synthetic, Jira-shaped) | nothing by default; swap for a real Jira connection any time, see `docs/dora-metrics.md` |
| Claude KPI report | `qa-kpi-report` skill (`make report`) | a working `claude` CLI locally, or `ANTHROPIC_API_KEY` in CI |

## Example report

`make report` (or the `qa-kpi-report.yml` workflow) runs the `qa-kpi-report` skill to turn the
week's numbers into a short narrative like this one. [`reports/2026-09-03.md`](reports/2026-09-03.md)
is a real example generated against `make demo`'s synthetic seed data:

> Overall pass rate slipped from 94.3% to 86.7% week-over-week, driven almost entirely by
> `backend-agentic`: its GraphQL suite's `test_query_order` started failing on 2026-08-28 and
> hasn't recovered, dragging that repo's CI success rate to 0% for the week (down from 57.1%).
> `playwright-agentic` also softened (CI success 71.4% → 50.0%) but stayed above a 90% pass
> rate; `k6-agentic` held steady at 100%.
>
> **Recommended actions:** quarantine `test_query_order` and investigate the GraphQL
> schema/resolver change around 2026-08-28 — it's the single highest-leverage fix...

See the full file for the DORA/regressions/flaky-tests breakdown and the rest of the
recommendations.

## Repo layout

```
config/sources.yaml    The one file to edit to point this at a different org/repos
qa_collector/           Test-result ingestion: GitHub Actions artifacts -> qa-postgres
devlake/scripts/         DevLake connection/scope config-as-code
scripts/seed/             Synthetic demo data generator
grafana/                  Provisioned datasource + the QA Automation KPIs / Test Case History dashboards
docs/                     Metric definitions and DORA source mapping
.github/workflows/        The always-on ingestion + weekly report pipelines (for a real deployment)
.claude/skills/           Claude Code skills for operating this stack (see CLAUDE.md)
```

## Why these three repos

`playwright-agentic`, `k6-agentic`, and `backend-agentic` are this org's existing QA automation frameworks (Playwright E2E/API, k6 performance, pytest backend), each already following a Claude Code "constitution + skills" pattern of their own. This dashboard is the natural next layer on top: turn what those frameworks already produce in CI into KPIs a team actually watches.
