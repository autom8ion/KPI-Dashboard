---
name: dashboard-authoring
description: Use when adding, editing, or debugging a Grafana panel or dashboard in this repo -- a new KPI panel on QA Automation KPIs, a new dashboard, a broken query, or a datasource/provisioning problem. Trigger phrases like "add a panel for X", "create a new dashboard", "why is this panel empty", "the qa-postgres datasource isn't showing up".
---

# Grafana dashboard authoring

Goal: dashboards and datasources here are provisioned as code (`grafana/provisioning/`, `grafana/dashboards/*.json`) -- never hand-edit a panel in the Grafana UI and expect it to survive; edit the JSON and let provisioning reload it (`updateIntervalSeconds: 30` in `grafana/provisioning/dashboards/dashboards.yml`).

## 1. The two datasources, and which one a new panel needs

- **`qa-postgres`** (uid `qa-postgres`) -- `qa_collector`'s own schema: `test_runs`, `test_case_results`, `flaky_tests`, and the `v_test_case_results` convenience view (join of the first two). Use this for anything test-case-level: pass rate, flaky tests, duration, tags, CI success rate. See `qa_collector/schema.sql` for the authoritative schema -- don't guess column names, read it.
- **DevLake's own MySQL datasource** -- provisioned automatically by DevLake's own Grafana image (not something this repo sets up). Use this only for DORA/PR/issue-level data that's genuinely DevLake's domain (deployments, change lead time, issues) -- and note DevLake's own DORA/Jira/Github dashboards (folder `General` in Grafana, distinct from this repo's `QA Automation` folder) already cover most of that; check those exist before building a duplicate panel here.

## 2. Adding a panel to `qa-automation-kpis.json`

1. Read the file first -- panels are plain Grafana dashboard JSON (schemaVersion 39), each with `gridPos`, a `datasource` block, and one `targets[].rawSql` postgres query.
2. Write the query against `v_test_case_results` (or `test_runs`/`flaky_tests` directly) and test it for real against the running qa-postgres before adding it to the JSON:
   ```bash
   docker compose exec qa-postgres psql -U qa -d qa_metrics -c "<your query>"
   ```
3. For a time-series panel, the postgres datasource plugin expects columns named `time`, `value`, and optionally `metric` (becomes the series legend) -- follow the existing panels' `AS time`/`AS metric`/`AS value` aliasing exactly, Grafana won't infer it otherwise.
4. Pick `gridPos` so the new panel doesn't overlap an existing one (24-column grid; look at the `y`/`h` of the panel above where you're inserting).
5. No restart needed -- provisioning polls every 30s. If it doesn't show up, check `docker compose logs grafana` for a JSON parse error first (a single malformed panel can fail the whole dashboard's reload).

## 3. Adding a whole new dashboard

Create `grafana/dashboards/<name>.json` (copy `qa-automation-kpis.json`'s top-level structure as a starting point: `id: null`, a unique `uid`, `schemaVersion: 39`). It's picked up automatically by the existing `qa-kpi-dashboards` provider (`grafana/provisioning/dashboards/dashboards.yml`) -- no new provisioning file needed unless it needs a different folder or a different datasource requiring new provisioning.

## 4. Debugging an empty/broken panel

- Query returns nothing in `psql` but should have rows: check the time range in the dashboard (top right) against `WHERE run_started_at >= now() - interval '...'` in the query -- a common mismatch.
- Panel shows a datasource error: confirm `qa-postgres` resolved (Grafana -> Connections -> Data sources) -- if missing, check `docker-compose.yml`'s volume mounts for `grafana/provisioning/datasources/qa-postgres.yml` actually landed at `/etc/grafana/provisioning/datasources/` (a typo'd host path fails silently, Grafana just doesn't see the file).
- Table panel columns look unlabeled/wrong: postgres `format: "table"` just returns your `SELECT` columns as-is -- rename columns with `AS` for anything you want a nicer header on.
