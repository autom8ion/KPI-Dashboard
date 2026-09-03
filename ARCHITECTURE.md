# Architecture

## Problem

Get QA automation + engineering KPIs — DORA metrics and test-level health (pass rate, flaky tests, CI health) — into one dashboard, fed by GitHub Actions and (optionally) Jira, for three existing test-automation repos in this org (`playwright-agentic`, `k6-agentic`, `backend-agentic`).

## Why Apache DevLake + Grafana, plus a custom piece

[Apache DevLake](https://devlake.apache.org/) is the standard open-source choice for this: it ingests GitHub/GitLab/Jenkins/Jira/etc. into a unified domain schema and computes DORA metrics from it out of the box, with a Grafana OSS frontend it provisions itself. Using it instead of hand-rolling GitHub/Jira ETL is most of this repo's leverage.

**What it doesn't do**: test-case-level results. DevLake's plugins give it commits, PRs, issues, and CI *pipeline* runs (`cicd_pipelines`/`cicd_tasks`) — enough for DORA — but nothing at the level of "which test cases passed, which are flaky, how long did the suite take." There is no JUnit/test-report plugin. That gap is `qa_collector`, a small pipeline with its own database (`qa-postgres`), visualized in the same Grafana instance via a second datasource.

## Data flow

```
GitHub Actions (autom8ion org)
  playwright-agentic, k6-agentic, backend-agentic, KPI-Dashboard
        │                                    │
        │ GitHub REST API                    │ CI artifacts
        │ (commits, PRs, issues,             │ (JUnit XML, k6 summary JSON, CTRF —
        │  workflow runs)                    │  see sibling repos' CI changes)
        ▼                                    ▼
┌────────────────────────┐        ┌──────────────────────────┐
│ Apache DevLake          │        │ qa_collector (custom)     │
│ github + (optional)     │        │ fetch → parse → normalize │
│ jira plugins, config    │        │ → flaky-detect → load     │
│ via devlake/scripts/    │        └─────────────┬─────────────┘
│ bootstrap.sh             │                      │ writes
└────────────┬─────────────┘                      ▼
             │ writes                    ┌──────────────────┐
             ▼                            │ qa-postgres        │
   ┌──────────────────┐                  │ test_runs           │
   │ DevLake MySQL     │                  │ test_case_results    │
   │ (domain layer)    │                  │ flaky_tests           │
   └─────────┬─────────┘                  └─────────┬─────────────┘
             │                                       │
             └───────────────┬───────────────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │ Grafana (DevLake's own    │
                  │ image, one extra          │
                  │ datasource + dashboard)   │
                  │  - DORA, Jira, Github,     │
                  │    Homepage (DevLake's own)│
                  │  - QA Automation KPIs      │
                  │    (this repo's addition)  │
                  └────────────┬───────────────┘
                               │ queried directly (not screen-scraped)
                               ▼
                  ┌─────────────────────────┐
                  │ qa-kpi-report skill        │
                  │ → narrative Markdown        │
                  │ → reports/, optionally Slack │
                  └─────────────────────────┘
```

Jira: seeded via `scripts/seed/generate_sample_data.py` (synthetic bugs/incidents pushed through DevLake's **webhook plugin**, not a real Jira connection) so bug-trend/MTTR panels populate without a live Jira instance. `docs/dora-metrics.md` documents swapping in a real one.

## Why a separate `qa-postgres` instead of extra tables in DevLake's MySQL

DevLake owns and migrates its own schema (`_tool_*`, domain-layer tables) as part of normal upgrades; bolting custom tables onto that database would risk breaking on a DevLake version bump, and gives `qa_collector` no schema stability guarantee to build against. A separate, small, hand-owned Postgres (`qa_collector/schema.sql`) is the standard pattern for "DevLake plus something it doesn't do natively" — it survives independent upgrades of either side, and `qa_collector` never needs to understand DevLake's internal schema at all.

## Why DevLake's Project/Blueprint creation is a manual step

`devlake/scripts/bootstrap.sh` scripts everything with a well-documented, stable API surface: creating a GitHub (and optionally Jira) connection, a DORA-oriented scope config (`issueTypeBug`/`issueTypeIncident`/`deploymentPattern`/`productionPattern`), and attaching repos as scopes — all verified directly against DevLake v1.0.3-beta16's own API source (`backend/plugins/github/{api,models}/*.go`). Project and Blueprint creation is a different kind of API surface (a multi-entity wizard flow DevLake's own maintainers point users at the Config UI for); scripting it would mean guessing at a payload shape with real risk of being subtly wrong in a way a demo user can't debug. The honest tradeoff: script what's reliably scriptable, leave a ~2-minute UI step for the rest, and say so plainly (see the script's own header comment and the `devlake-bootstrap` skill).

## Why DORA/deployment signal is seeded rather than live for these three repos

`playwright-agentic`, `k6-agentic`, `backend-agentic` are QA **test-framework** repos, not deployable applications — none of their CI jobs represent a real production deploy. DORA's Deployment Frequency/Change Failure Rate fundamentally measure how an *application* ships; applying them to test-tooling repos by treating "CI went green" as "we deployed" would be a fabricated metric, not a demo simplification. `devlake/scripts/bootstrap.sh` leaves `deploymentPattern`/`productionPattern` blank for exactly this reason (see `docs/dora-metrics.md`), and the demo's DORA panels are populated from `scripts/seed/generate_sample_data.py`'s synthetic deployments/incidents instead — clearly labeled as such, not presented as real signal from these repos.

## `qa-postgres` schema reference

See `qa_collector/schema.sql` for the authoritative definitions (kept in one file deliberately, so it's never out of sync with itself). Summary:

- **`repos`** — the three (four, including this repo) known source repos.
- **`test_runs`** — one row per (repo, GitHub Actions workflow run, artifact group/job). Idempotent upsert key: `(repo_id, workflow_run_id, job_name)`.
- **`test_case_results`** — one row per test case per run, `ON DELETE CASCADE` from `test_runs`.
- **`flaky_tests`** — maintained by `qa_collector/flaky_detector.py`, recomputed on every ingest.
- **`v_test_case_results`** — the join view almost every Grafana query and report query actually wants (test case + its run's repo/branch/commit/timestamp).

## Claude Code skills

Five skills in `.claude/skills/` cover operating this stack — see `CLAUDE.md`'s skills index for the one-line router. The one worth calling out architecturally is `qa-kpi-report`: it's the one component in this whole design where an LLM is doing something a dashboard genuinely can't — judging which of several simultaneous numeric trends in a given week actually matters, and saying so in two sentences instead of making a human stare at eight panels.
