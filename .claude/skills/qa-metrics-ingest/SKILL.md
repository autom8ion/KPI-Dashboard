---
name: qa-metrics-ingest
description: Use when running, debugging, or extending qa_collector -- the test-level (pass/fail/flaky/duration) ingestion pipeline that fills the gap DevLake doesn't cover. Covers running an ingest for one/all repos, backfilling history, debugging a missing/wrong artifact, and adding a parser for a new test-result format. Trigger phrases like "ingest test results", "why is a run missing from qa-postgres", "backfill test history", "add a parser for X".
---

# qa_collector: run, debug, extend

Goal: get real (not seeded) test-case-level data from GitHub Actions artifacts into `qa-postgres`, and know how to add support for a format qa_collector doesn't parse yet.

## 1. Run an ingest

```bash
set -a && . ./.env && set +a           # needs GITHUB_TOKEN, QA_POSTGRES_DSN
python -m qa_collector.run                                    # every repo in config/sources.yaml with a framework set
python -m qa_collector.run --repo playwright-agentic --limit 5
```

Which repos it knows about, and which parser each one routes to, comes from `config/sources.yaml` (via `qa_collector/config.py`) -- not a hardcoded list in `run.py`. See README.md "Plugging in your own repos".

Idempotent: re-running re-fetches and upserts (`qa_collector/normalize.py`'s `upsert_test_run`) rather than duplicating rows, keyed on `(repo_id, workflow_run_id, job_name)`. It also runs the flaky-test detector (`qa_collector/flaky_detector.py`) at the end of every ingest -- no separate step needed.

## 2. What it actually pulls

`qa_collector/github_fetch.py` lists each repo's recently *completed* workflow runs, then downloads whichever of these artifacts that run published (see the sibling repos' CI, and `KNOWN_ARTIFACT_NAMES` in that file):

| Artifact name | Repo | Parser |
|---|---|---|
| `junit-results` | playwright-agentic, backend-agentic | `parsers/junit_parser.py` (`.xml`) |
| `k6-summary`, `k6-db-summary` | k6-agentic | `parsers/k6_parser.py` (`.json`) |
| `ctrf-report` | any repo with a [CTRF](https://ctrf.io) reporter | `parsers/ctrf_parser.py` (`.json`) |

`.xml` files always go to the JUnit parser. `.json` files are **content-sniffed**, not routed by filename/artifact name (`run.py`'s `_cases_for_artifact`) -- `is_ctrf_report()` checks for `results.tests` before falling back to the k6-summary parser, so a CTRF artifact works even if a CI step named it something other than `ctrf-report` (as long as the name is in `KNOWN_ARTIFACT_NAMES`, or you add it there).

Each artifact group becomes one `test_runs` row (job_name = artifact name), so e.g. k6-agentic's rest/graphql/db smoke jobs show up as separate rows under the same GitHub Actions run.

CTRF's own `flaky: true` field (set by a reporter when a retry within the same run changed status -- a stronger signal than our own history-based detection) is surfaced as a `ctrf-flaky` tag on the test case rather than a schema change, so it flows through the same tag-breakdown panel as everything else.

k6 additionally gets its own performance-metrics path: each k6-summary/k6-db-summary `.json` file is also passed to `parsers/k6_parser.py`'s `parse_k6_metrics`, and the result (if any) is upserted into `k6_run_metrics` keyed on `(test_run_id, source_file)` -- see `docs/qa-kpis.md` "k6 performance metrics" and the `k6-performance` Grafana dashboard. `source_file` matters here: one `k6-summary` artifact can zip up multiple `--summary-export` files for different scripts (e.g. a REST one and a GraphQL one), so this is per-file, not per-job.

## 2a. A note on trusting this pipeline's own claims about k6

`k6-agentic` had zero GitHub Actions runs with a downloadable artifact for a long stretch (every run either failed before the upload step or the artifact had expired) -- which meant the k6 code paths in `k6_parser.py`/`run.py` had never actually been exercised against a real `--summary-export` file, only against hand-written/guessed fixtures. The first time a real artifact *did* show up, ingestion crashed immediately (`_walk_checks` assumed `checks`/`groups` were lists; the real export has them as dicts keyed by name -- fixed, but check `_children()` in `k6_parser.py` if a future k6-agentic version regresses this again). The lesson: a k6 code path that's only ever been tested against zero real runs is unverified, not working -- if you're touching `k6_parser.py`, pull one real artifact (`python -c "from qa_collector import github_fetch; ..."` or `gh run download`) and run it through before trusting the diff, rather than assuming the existing shape comments are still accurate.

## 3. Debugging a missing or wrong run

- Nothing ingested for a repo: check the run actually uploaded a known artifact (`gh run view <run-id> --repo autom8ion/<repo>`) -- a run that failed before the upload step (e.g. lint failure) has nothing to pull.
- `GITHUB_TOKEN` needs `actions:read`/`contents:read` on every repo in `config/sources.yaml`, not just KPI-Dashboard.
- Wrong tags/suite grouping: read the comment at the top of `parsers/junit_parser.py` -- pytest tag inference is a heuristic (first path segment after `tests/`), not a real marker read, since default `--junitxml` drops markers.
- k6 parsing looks empty/wrong: k6's `--summary-export` JSON shape has moved before; see the comment at the top of `parsers/k6_parser.py`, and check what k6-agentic's pinned k6 version actually emits with a manual `k6 run --summary-export=/tmp/s.json ...` before assuming the parser is broken.
- A k6 `threshold: <expr>` TestCase's pass/fail looks backwards (e.g. shows failed when the metric's own reported value clearly satisfies the expression, or vice versa): a real k6-agentic export was observed reporting a bare boolean per threshold (`"thresholds": {"p(95)<800": false}`) that did **not** reliably match "did this threshold pass" when checked against that same metric's own numeric value in the same file -- it may represent `abortOnFail` or some other config flag serialized into that position rather than a pass/fail outcome, depending on k6 version. `parse_k6_summary`'s current handling (`ok = bool(result)` when the value isn't a dict) was not changed to work around this since the correct fix -- actually evaluating the threshold expression against the metric's own values, rather than trusting either polarity of a bare boolean -- is a real (if small) expression-evaluator, not a one-line flip. Verify against a real export's own numbers before trusting either the test case status or a quick polarity flip.
- A `.json` artifact got parsed as the wrong format: check `is_ctrf_report()` in `parsers/ctrf_parser.py` -- it only requires `results.tests` to be a list, so a k6 summary would misroute *to* CTRF only if it happened to have that exact shape (it doesn't, by default). If a custom k6 setup or a different tool's export does collide, tighten the sniff (e.g. also check `results.tool`) rather than switching back to name-based routing.

## 4. Backfilling more history

Bump `--limit` (default 20) -- `github_fetch.list_recent_runs` just raises `per_page` on the GitHub Actions API call. There's no separate backfill mode by design; a large `--limit` against three repos' worth of history is cheap enough for a demo-scale project not to need one.

## 5. Adding a new test-result format

1. Add a `qa_collector/parsers/<format>_parser.py` with one function returning `list[qa_collector.normalize.TestCase]`, following `junit_parser.py`'s shape (it's the simplest reference) -- or, if the framework has a CTRF reporter available, prefer producing CTRF in CI over writing a new parser at all (see `new-source-onboarding`).
2. Wire it into `run.py`'s `_cases_for_artifact` by file extension, or content-sniff it the way `ctrf_parser.is_ctrf_report()` does if it shares an extension with an existing format.
3. Add the new artifact name to `KNOWN_ARTIFACT_NAMES` in `github_fetch.py`.
4. If it's for a genuinely new repo (not a new format for an existing one), use `new-source-onboarding` instead -- it covers this plus the DevLake and seed-data sides together.
