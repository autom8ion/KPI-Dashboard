---
name: devlake-bootstrap
description: Use when configuring or troubleshooting DevLake's connections, repo scopes, or DORA scope-config in this repo -- setting up a new GitHub/Jira connection, re-running bootstrap after DevLake resets, debugging a failed collection pipeline, or swapping seeded Jira for a real instance. Trigger phrases like "set up DevLake", "add a repo to DevLake", "why isn't DevLake collecting", "connect a real Jira instance", "the blueprint failed".
---

# DevLake bootstrap & troubleshooting

Goal: get DevLake's GitHub connection, repo scopes, and DORA scope-config into a known-good state via its REST config API (config-as-code, not manual UI clicking), and know where the one deliberately-manual step is.

## What's scripted vs. manual

`devlake/scripts/bootstrap.sh` is idempotent and handles: the `autom8ion-github` connection, the `qa-automation-dora` scope config (issue-type mapping + deployment/production regex), and attaching the four `autom8ion` repos as scopes. It does **not** create the DevLake Project or Blueprint -- see the comment at the top of that script for why (DevLake's own maintainers recommend the Config UI wizard for that step; a hand-crafted blueprint JSON payload is the part of the API that's genuinely fragile to script correctly).

## 1. Run/re-run bootstrap

```bash
set -a && . ./.env && set +a
bash devlake/scripts/bootstrap.sh
```

Safe to re-run any time -- it looks up existing connections/scope-configs by name before creating new ones. If `GITHUB_TOKEN` is blank in `.env`, it exits early and prints why (the demo still works off seeded data).

## 2. Finish the one manual step

Follow the script's printed instructions: `http://localhost:4000` -> Projects -> New Project ("qa-automation") -> add the connection's scopes -> Save -> "Collect Data Now". This only needs to happen once per fresh DevLake database (i.e. not after every `bootstrap.sh` re-run, only after `make clean` / a fresh `mysql-storage` volume).

## 3. Troubleshooting a failed collection

- Config UI -> Blueprints -> the failed run -> expand the failing subtask for the actual error (usually a GitHub rate limit, a bad token scope, or a repo the token can't see).
- `docker compose logs devlake --tail 200` for the lake process's own errors (migration issues, DB connectivity).
- A `401`/`403` from GitHub almost always means the PAT is missing `repo`/`read:org` scope, or (for org repos) SSO isn't authorized for the token.
- If scopes silently show no data after a run: check the scope config actually attached (`GET /plugins/github/connections/{id}/scopes` should show `scopeConfigId` set on each repo) -- `bootstrap.sh` sets this, but a repo added by hand through the UI won't have it unless you pick "qa-automation-dora" in the scope's edit dialog.

## 4. Swapping seeded Jira for a real instance

Set `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` in `.env` and re-run `bash devlake/scripts/bootstrap.sh` -- it creates an `autom8ion-jira` connection. Then in the Config UI: Connections -> autom8ion-jira -> Add Data Scope -> pick the board(s). Add that connection's scopes to the "qa-automation" project the same way as GitHub's. From then on, real Jira issues (not `scripts/seed/generate_sample_data.py`'s synthetic ones) drive the bug-trend and MTTR panels -- see `docs/dora-metrics.md`.

## 5. Adding a repo/connection later

See the `new-source-onboarding` skill -- it covers both the DevLake side (this skill's `bootstrap.sh` pattern) and the qa_collector side together, since a new repo usually needs both.
