# DORA metrics: source mapping

DevLake computes all four DORA metrics itself (`backend/plugins/dora`) once it has enough raw data: pull requests, deployments, and incidents. This repo's job is only to get that raw data in — either from real GitHub/Jira connections, or, for the demo, seeded synthetic events via DevLake's webhook plugin.

| Metric | Real source (if connected) | Demo source | Notes |
|---|---|---|---|
| **Deployment Frequency** | GitHub Actions workflow runs matching the GitHub scope config's `deploymentPattern`/`productionPattern` regex | `scripts/seed/generate_sample_data.py` — one synthetic `PRODUCTION` deployment/day via `POST /plugins/webhook/connections/by-name/{name}/deployments` | See "Why deployment pattern is blank" below |
| **Lead Time for Changes** | GitHub PRs: merge time -> deploy time, via DevLake's GitHub plugin | Same seeded deployments, correlated by DevLake against seeded/real PR data | No custom code — DevLake's own calculation |
| **Change Failure Rate** | Deployments whose GitHub Actions run failed, or GitHub issues labeled per `issueTypeBug`/`issueTypeIncident` in the scope config | ~8% of seeded deployments marked `"result": "FAILURE"` | `devlake/scripts/bootstrap.sh` sets `issueTypeBug: "bug"`, `issueTypeIncident: "incident"` |
| **Mean Time to Restore (MTTR)** | Jira incidents (real connection), or GitHub issues typed as incidents | One seeded issue, `type: "INCIDENT"`, with `resolutionDate` ~3h45m after `createdDate` | See `WebhookIssueRequest` shape in `scripts/seed/generate_sample_data.py` |

## Why `deploymentPattern`/`productionPattern` are blank by default

`playwright-agentic`, `k6-agentic`, and `backend-agentic` are QA **test-framework** repos — none of their CI jobs represent an actual production deploy of an application. Setting a `deploymentPattern` that matched, say, their `CI` workflow would misrepresent "a test suite ran" as "we shipped to production," which is a worse and more misleading demo than just being honest that these three repos don't produce real deployment signal.

If you connect a real, deployable application repo:

```bash
DEPLOYMENT_PATTERN='^Deploy$|^Release$' PRODUCTION_PATTERN='^production$' bash devlake/scripts/bootstrap.sh
```

DevLake matches `deploymentPattern` against workflow/job names and `productionPattern` against the environment name; see DevLake's own [DORA docs](https://devlake.apache.org/docs/DORA/) for the general mechanism.

## Swapping in real Jira

1. Set `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` in `.env`.
2. Re-run `bash devlake/scripts/bootstrap.sh` — it creates an `autom8ion-jira` DevLake connection.
3. In the Config UI (`http://localhost:4000`): Connections -> `autom8ion-jira` -> Add Data Scope -> pick the board(s) -> add those scopes to the `qa-automation` project alongside the GitHub scopes.
4. From the next blueprint run onward, real Jira issues drive MTTR/bug-trend numbers instead of the two seeded issues. The seed script's synthetic Jira-shaped data (pushed via the webhook plugin, not a Jira connection) keeps running unless you also stop calling `scripts/seed/generate_sample_data.py` — for a real deployment, drop that call from your setup once a real Jira is connected.

## DORA dashboard

DevLake's own Grafana image provisions a full **DORA** dashboard (plus per-metric detail dashboards, Jira, Github, Homepage) automatically — nothing in this repo needs to build or vendor that. It lives in Grafana's default (`General`) folder, next to this repo's own **QA Automation** folder. Select the `qa-automation` project (created in the manual bootstrap step, see the `devlake-bootstrap` skill) in its project picker.
