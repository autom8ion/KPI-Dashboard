---
name: qa-kpi-report
description: Generate a narrative Markdown QA KPI report from the current qa-postgres/DevLake numbers -- headline metrics, notable regressions/improvements, flaky-test callouts, and suggested actions. Use when asked for a QA KPI report, a weekly summary, "what changed this week", or when the qa-kpi-report.yml workflow / `make report` invokes this skill directly. Trigger phrases like "generate the QA report", "summarize this week's test health", "what's changed in the dashboard".
---

# QA KPI report generation

Goal: turn the numbers Grafana already shows into a short, prioritized narrative -- this is the one piece of this stack a dashboard genuinely can't do on its own: judging which of several simultaneous trends actually matters this week, and saying so in plain language.

## 1. Pull the numbers

Query `qa-postgres` directly (fastest, most reliable -- don't scrape Grafana's rendered panels):

```bash
set -a && . ./.env && set +a
psql "$QA_POSTGRES_DSN" -c "<query>"
```

Pull, for the trailing 7 days vs. the 7 days before that (week-over-week comparison is what makes the narrative meaningful, not a single snapshot):
- Overall pass rate and pass rate per repo (`v_test_case_results`, same shape as the dashboard's pass-rate panels -- see `dashboard-authoring` skill for the exact query pattern).
- CI success rate per repo (`test_runs.conclusion`).
- Active flaky tests (`flaky_tests WHERE is_active`), and which ones are *new* this week (`first_seen_at` in the last 7 days) vs. long-standing.
- Mean test duration trend -- flag a repo whose mean duration moved >20% either direction.
- Top failure messages/tags (`v_test_case_results WHERE status='failed'`, grouped) -- look for one root cause behind several failing tests, not just a flat list.

If `DEVLAKE_API_URL`/`DEVLAKE_GRAFANA_URL` are reachable, also pull DORA headline numbers (deployment frequency, change failure rate, lead time, MTTR) from DevLake's project dashboard for the same window -- optional, don't fail the report if DevLake isn't reachable, just omit that section and say so.

## 2. Write the narrative

Not a data dump -- the value-add is judgment. Structure:

1. **Headline** (2-3 sentences): the single most important thing that changed, stated plainly (e.g. "Pass rate held steady at 97% except backend-agentic's GraphQL suite, which regressed from 98% to 71% on Tuesday and hasn't recovered").
2. **DORA** (if available): the four numbers, one line each, with direction vs. last week.
3. **Notable regressions**: name the specific test(s)/suite(s), when it started, and — if the error messages point to one — a best guess at cause. Don't hedge every sentence; state the evidence and the confidence level once.
4. **Flaky tests**: new ones this week, and any long-standing one whose flip_count got worse.
5. **Recommended actions**: 2-4 concrete, specific items (e.g. "Quarantine `test_query_order` (failing since day 24, backend-agentic) until the GraphQL schema regression is fixed" -- not generic advice like "investigate flaky tests more").

Keep it tight -- this is a report a person reads in under a minute, not a full data appendix. Link back to the Grafana dashboard (`$DEVLAKE_GRAFANA_URL`) for anyone who wants to drill in themselves rather than reproducing every chart in prose.

## 3. Deliver it

Write to `reports/<YYYY-MM-DD>.md` (today's date). If invoked from `qa-kpi-report.yml`, that workflow commits and pushes it, and optionally posts to Slack -- this skill's job ends at writing the file. If run interactively (`make report` or asked directly), also print the headline section to the terminal.
