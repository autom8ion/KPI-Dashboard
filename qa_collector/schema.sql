-- qa-postgres schema: test-level QA KPIs that Apache DevLake does not
-- natively ingest (DevLake's GitHub/Jira/Jenkins plugins give it commits,
-- PRs, issues, and CI *pipeline* runs -- enough for DORA -- but nothing at
-- the level of "which test cases passed, which are flaky"). This database
-- is owned entirely by qa_collector; DevLake never reads or writes it, and
-- nothing here depends on DevLake's own schema, so it survives independent
-- upgrades of either side. See ARCHITECTURE.md.

-- Rows are synced from config/sources.yaml by qa_collector/db.py's
-- ensure_schema() on every run, not seeded here -- see that module.
CREATE TABLE IF NOT EXISTS repos (
    id              TEXT PRIMARY KEY,           -- matches config/sources.yaml's repo id
    github_org      TEXT NOT NULL,
    github_repo     TEXT NOT NULL,
    framework       TEXT NOT NULL,               -- 'playwright' | 'pytest' | 'k6'
    UNIQUE (github_org, github_repo)
);

-- One row per (repo, GitHub Actions workflow run, job). A run with a
-- matrix or multiple relevant jobs (e.g. rest + graphql + db smoke tests
-- in k6-agentic) gets one test_runs row per job so panels can break down
-- by job as well as by repo.
CREATE TABLE IF NOT EXISTS test_runs (
    id                  BIGSERIAL PRIMARY KEY,
    repo_id             TEXT NOT NULL REFERENCES repos(id),
    workflow_run_id     BIGINT NOT NULL,
    workflow_name       TEXT NOT NULL,
    job_name            TEXT NOT NULL DEFAULT '',
    branch              TEXT NOT NULL,
    commit_sha          TEXT NOT NULL,
    triggered_by        TEXT,                    -- push | pull_request | schedule | workflow_dispatch | seed
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    conclusion          TEXT,                    -- success | failure | cancelled
    source              TEXT NOT NULL,            -- junit | k6-summary | seed
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repo_id, workflow_run_id, job_name)
);

CREATE INDEX IF NOT EXISTS idx_test_runs_repo_started ON test_runs (repo_id, started_at DESC);

CREATE TABLE IF NOT EXISTS test_case_results (
    id              BIGSERIAL PRIMARY KEY,
    test_run_id     BIGINT NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    suite           TEXT NOT NULL,                -- spec file / test class / k6 script
    test_name       TEXT NOT NULL,
    tags            TEXT[] NOT NULL DEFAULT '{}', -- @smoke/@api/... (playwright), marker (pytest), check name (k6)
    status          TEXT NOT NULL,                -- passed | failed | skipped
    duration_ms     INTEGER,
    error_message   TEXT,
    UNIQUE (test_run_id, suite, test_name)
);

CREATE INDEX IF NOT EXISTS idx_tcr_run ON test_case_results (test_run_id);
CREATE INDEX IF NOT EXISTS idx_tcr_status ON test_case_results (status);

-- Maintained by flaky_detector.py: a test earns a row here once it has
-- alternated pass/fail across its last N runs on the same branch. Grafana's
-- flaky-leaderboard panel reads this table directly instead of recomputing
-- flip-detection in PromQL/SQL on every dashboard load.
CREATE TABLE IF NOT EXISTS flaky_tests (
    id              BIGSERIAL PRIMARY KEY,
    repo_id         TEXT NOT NULL REFERENCES repos(id),
    suite           TEXT NOT NULL,
    test_name       TEXT NOT NULL,
    branch          TEXT NOT NULL,
    first_seen_at   TIMESTAMPTZ NOT NULL,
    last_seen_at    TIMESTAMPTZ NOT NULL,
    flip_count      INTEGER NOT NULL DEFAULT 1,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (repo_id, suite, test_name, branch)
);

-- Convenience join for Grafana panels -- almost every query wants
-- test_case_results alongside its run's repo/branch/commit/timestamp.
CREATE OR REPLACE VIEW v_test_case_results AS
SELECT
    tcr.id,
    tcr.suite,
    tcr.test_name,
    tcr.tags,
    tcr.status,
    tcr.duration_ms,
    tcr.error_message,
    tr.id           AS test_run_id,
    tr.repo_id,
    tr.branch,
    tr.commit_sha,
    tr.workflow_name,
    tr.job_name,
    tr.source,
    tr.started_at   AS run_started_at
FROM test_case_results tcr
JOIN test_runs tr ON tr.id = tcr.test_run_id;

-- k6's --summary-export gives per-check/per-threshold pass-fail (already
-- captured as test_case_results rows tagged k6-check/k6-threshold) *and* a
-- separate "metrics" object of run-level performance aggregates that don't
-- fit the pass/fail shape at all -- latency percentiles, throughput, error
-- rate, concurrency. This table is qa_collector/parsers/k6_parser.py's
-- parse_k6_metrics() write target (via normalize.upsert_k6_metrics).
-- Nullable throughout: k6's default summaryTrendStats only guarantees
-- avg/min/med/max/p(90)/p(95) -- p(99) (and http_req_failed, added in k6
-- v0.31) are only present if the pinned k6 version/config reports them, so
-- a missing column here means "the run didn't report this stat", not a
-- collector bug.
--
-- Keyed on (test_run_id, source_file), not just test_run_id: one artifact
-- (one test_runs row, e.g. k6-agentic's "k6-summary" job) can bundle
-- multiple --summary-export files for genuinely different k6 scripts with
-- different load profiles (confirmed against a real k6-agentic run:
-- k6-summary/k6-rest-summary.json and k6-summary/k6-graphql-summary.json
-- both land under one job_name) -- collapsing them to one row per run
-- would silently overwrite one script's numbers with the other's.
--
-- Deliberately one aggregate row per (run, script), trended across runs
-- over time (same pattern as duration_ms in test_case_results) rather than
-- a per-second time series within a run -- that finer-grained view is a
-- different k6 output mode entirely (xk6-output-prometheus-remote or
-- InfluxDB streaming *during* the load test), which this repo's "parse an
-- artifact after CI finishes" architecture doesn't produce. What's here
-- answers "is this endpoint's performance drifting build over build", not
-- "show me this run's live VU ramp" -- see docs/qa-kpis.md.
CREATE TABLE IF NOT EXISTS k6_run_metrics (
    test_run_id                 BIGINT NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    source_file                 TEXT NOT NULL DEFAULT '',  -- e.g. 'k6-rest-summary.json'; '' for seeded/single-file runs
    vus_max                     INTEGER,
    http_reqs_count             INTEGER,
    http_reqs_rate              DOUBLE PRECISION,  -- requests/sec
    http_req_failed_rate        DOUBLE PRECISION,  -- 0..1
    http_req_duration_avg_ms    DOUBLE PRECISION,
    http_req_duration_p90_ms    DOUBLE PRECISION,
    http_req_duration_p95_ms    DOUBLE PRECISION,
    http_req_duration_p99_ms    DOUBLE PRECISION,  -- often NULL, see comment above
    http_req_duration_max_ms    DOUBLE PRECISION,
    iterations_count            INTEGER,
    iterations_rate             DOUBLE PRECISION,  -- iterations/sec
    data_received_bytes         BIGINT,
    data_sent_bytes             BIGINT,
    PRIMARY KEY (test_run_id, source_file)
);

-- Convenience join, mirroring v_test_case_results, for panels that want a
-- k6 run's performance metrics alongside its repo/branch/commit/timestamp.
CREATE OR REPLACE VIEW v_k6_run_metrics AS
SELECT
    krm.*,
    tr.repo_id,
    tr.job_name,
    tr.branch,
    tr.commit_sha,
    tr.workflow_run_id,
    tr.conclusion,
    tr.started_at AS run_started_at
FROM k6_run_metrics krm
JOIN test_runs tr ON tr.id = krm.test_run_id;
