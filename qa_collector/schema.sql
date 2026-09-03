-- qa-postgres schema: test-level QA KPIs that Apache DevLake does not
-- natively ingest (DevLake's GitHub/Jira/Jenkins plugins give it commits,
-- PRs, issues, and CI *pipeline* runs -- enough for DORA -- but nothing at
-- the level of "which test cases passed, which are flaky"). This database
-- is owned entirely by qa_collector; DevLake never reads or writes it, and
-- nothing here depends on DevLake's own schema, so it survives independent
-- upgrades of either side. See ARCHITECTURE.md.

CREATE TABLE IF NOT EXISTS repos (
    id              TEXT PRIMARY KEY,           -- e.g. 'playwright-agentic', matches qa_collector config
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

INSERT INTO repos (id, github_org, github_repo, framework) VALUES
    ('playwright-agentic', 'autom8ion', 'playwright-agentic', 'playwright'),
    ('backend-agentic',    'autom8ion', 'backend-agentic',    'pytest'),
    ('k6-agentic',         'autom8ion', 'k6-agentic',         'k6')
ON CONFLICT (id) DO NOTHING;
