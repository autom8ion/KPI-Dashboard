---
name: qa-metrics-ingest
description: Use when running, debugging, or extending qa_collector -- the test-level (pass/fail/flaky/duration) ingestion pipeline that fills the gap DevLake doesn't cover. Covers running an ingest for one/all repos, backfilling history, debugging a missing/wrong artifact, and adding a parser for a new test-result format. Trigger phrases like "ingest test results", "why is a run missing from qa-postgres", "backfill test history", "add a parser for X".
---

# qa_collector: run, debug, extend

Goal: get real (not seeded) test-case-level data from GitHub Actions artifacts into `qa-postgres`, and know how to add support for a format qa_collector doesn't parse yet.

## 1. Run an ingest

```bash
set -a && . ./.env && set +a           # needs GITHUB_TOKEN, QA_POSTGRES_DSN
python -m qa_collector.run                                    # all three repos, last 20 runs each
python -m qa_collector.run --repo playwright-agentic --limit 5
```

Idempotent: re-running re-fetches and upserts (`qa_collector/normalize.py`'s `upsert_test_run`) rather than duplicating rows, keyed on `(repo_id, workflow_run_id, job_name)`. It also runs the flaky-test detector (`qa_collector/flaky_detector.py`) at the end of every ingest -- no separate step needed.

## 2. What it actually pulls

`qa_collector/github_fetch.py` lists each repo's recently *completed* workflow runs, then downloads whichever of these artifacts that run published (see the sibling repos' CI, and `KNOWN_ARTIFACT_NAMES` in that file):

| Artifact name | Repo | Parser |
|---|---|---|
| `junit-results` | playwright-agentic, backend-agentic | `parsers/junit_parser.py` |
| `k6-summary`, `k6-db-summary` | k6-agentic | `parsers/k6_parser.py` |

Each artifact group becomes one `test_runs` row (job_name = artifact name), so e.g. k6-agentic's rest/graphql/db smoke jobs show up as separate rows under the same GitHub Actions run.

## 3. Debugging a missing or wrong run

- Nothing ingested for a repo: check the run actually uploaded a known artifact (`gh run view <run-id> --repo autom8ion/<repo>`) -- a run that failed before the upload step (e.g. lint failure) has nothing to pull.
- `GITHUB_TOKEN` needs `actions:read`/`contents:read` on all three sibling repos, not just KPI-Dashboard.
- Wrong tags/suite grouping: read the comment at the top of `parsers/junit_parser.py` -- pytest tag inference is a heuristic (first path segment after `tests/`), not a real marker read, since default `--junitxml` drops markers.
- k6 parsing looks empty/wrong: k6's `--summary-export` JSON shape has moved before; see the comment at the top of `parsers/k6_parser.py`, and check what k6-agentic's pinned k6 version actually emits with a manual `k6 run --summary-export=/tmp/s.json ...` before assuming the parser is broken.

## 4. Backfilling more history

Bump `--limit` (default 20) -- `github_fetch.list_recent_runs` just raises `per_page` on the GitHub Actions API call. There's no separate backfill mode by design; a large `--limit` against three repos' worth of history is cheap enough for a demo-scale project not to need one.

## 5. Adding a new test-result format

1. Add a `qa_collector/parsers/<format>_parser.py` with one function returning `list[qa_collector.normalize.TestCase]`, following `junit_parser.py`'s shape (it's the simplest reference).
2. Wire it into `run.py`'s `_cases_for_artifact` by file extension or artifact-name prefix.
3. Add the new artifact name to `KNOWN_ARTIFACT_NAMES` in `github_fetch.py`.
4. If it's for a genuinely new repo (not a new format for an existing one), use `new-source-onboarding` instead -- it covers this plus the DevLake and seed-data sides together.
