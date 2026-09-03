---
name: new-source-onboarding
description: Router for adding a new repo/test-framework as a data source to the QA Automation KPI Dashboard -- what CI needs to export, what DevLake needs, and what qa_collector needs. Use when asked to add a 4th (or Nth) repo, wire up a new test framework, or connect a new application repo for real DORA data. Trigger phrases like "add a new repo to the dashboard", "onboard X to DevLake", "wire up test results for a new project".
---

# Onboarding a new source repo

Goal: a new repo needs three independent pieces wired up -- this skill is the checklist tying them together; each piece's actual mechanics live in a more specific skill.

## 1. CI must export a parseable test-result artifact

- **Prefer a [CTRF](https://ctrf.io) reporter if the framework has one** (Jest, Mocha, Cypress, Playwright, pytest via `pytest-ctrf-json`, and most others do) -- upload the JSON as an artifact named `ctrf-report` (or add its name to `KNOWN_ARTIFACT_NAMES`; it's content-sniffed, not name-routed, so any recognized artifact name works). This avoids writing a new parser at all, and CTRF's own `flaky`/`retries` fields give a better signal than JUnit XML carries.
- JUnit-XML-producing frameworks without a good CTRF reporter (Java/Kotlin via Maven/Gradle's default surefire output, etc.): add the flag, upload the XML as a workflow artifact named `junit-results` (matching `qa_collector.github_fetch.KNOWN_ARTIFACT_NAMES` -- or add a new name there, see step 2).
- k6: `--summary-export=<path>.json`, upload as an artifact name starting with `k6-` (see k6-agentic's CI for the two-step pattern needed when a job runs multiple k6 scripts, to avoid one export overwriting another).
- Anything else (a format qa_collector doesn't parse yet): see the `qa-metrics-ingest` skill's "Adding a new test-result format" section first.

## 2. qa_collector needs to know about the repo

In `qa_collector/run.py`'s `REPOS` dict, add `"<repo>": {"org": "...", "framework": "..."}`. In `qa_collector/schema.sql`'s seed `INSERT INTO repos`, add the matching row (or insert it directly -- the `ON CONFLICT DO NOTHING` makes either safe). If the new artifact name isn't already in `github_fetch.KNOWN_ARTIFACT_NAMES`, add it there too.

## 3. DevLake needs the repo as a scope (for DORA/PR/issue data)

Add the repo name to the `REPOS` array in `devlake/scripts/bootstrap.sh` and re-run it (see the `devlake-bootstrap` skill). If this is a real deployable application (not another test-framework repo like the current three), also set `DEPLOYMENT_PATTERN`/`PRODUCTION_PATTERN` env vars before running bootstrap -- see that script's comment for why they're blank by default for playwright-agentic/k6-agentic/backend-agentic.

## 4. Grafana

Existing `QA Automation KPIs` panels already aggregate by `repo_id` with no hardcoded repo list (check `grafana/dashboards/qa-automation-kpis.json` -- the queries `GROUP BY repo_id`/`metric`), so a correctly-onboarded repo shows up automatically once qa_collector has ingested at least one run. No dashboard edit needed unless you want a repo-specific panel -- see `dashboard-authoring` for that.

## 5. Verify end to end

1. Push the CI change, let a workflow run complete on the new repo.
2. `python -m qa_collector.run --repo <repo>` and confirm it prints a non-zero ingested count.
3. Check the new repo's rows appear in the `QA Automation KPIs` dashboard.
4. If DORA data matters for this repo, confirm in the Config UI that DevLake's collection picked it up (Blueprints -> latest run -> the new repo's tasks succeeded).
