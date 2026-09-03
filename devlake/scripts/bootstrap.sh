#!/usr/bin/env bash
# Configure DevLake's connections + repo scopes via its REST config API
# (config-as-code, not manual UI clicking) so `make demo` is reproducible.
#
# Verified against DevLake v1.0.3-beta15's actual API source
# (backend/plugins/github/{api,models}/*.go) rather than guessed:
#   POST /plugins/github/connections                    {name, endpoint, authMethod, token, enableGraphql}
#   PUT  /plugins/github/connections/{id}/scopes         {data: [{fullName, scopeConfigId}, ...]}
#   POST /plugins/github/connections/{id}/scope-configs  {name, issueTypeBug, issueTypeIncident,
#                                                          issueTypeRequirement, deploymentPattern,
#                                                          productionPattern}
#
# What this script does NOT do, on purpose: create the DevLake Project and
# Blueprint. That step is a short interactive wizard (Projects -> New
# Project -> pick this connection's scopes -> Save -> Collect Data Now) and
# is the one part of DevLake's own setup flow its maintainers recommend
# doing in the Config UI rather than by hand-crafting the blueprint JSON --
# see the printed instructions at the end of this script.
set -euo pipefail

: "${DEVLAKE_API_URL:=http://localhost:8080}"
: "${GITHUB_ORG:=autom8ion}"
: "${GITHUB_TOKEN:=}"
: "${JIRA_URL:=}"
: "${JIRA_EMAIL:=}"
: "${JIRA_API_TOKEN:=}"
# playwright-agentic/k6-agentic/backend-agentic are QA automation
# *test-framework* repos, not deployable applications -- none of their CI
# jobs represent a real production deploy, so DEPLOYMENT_PATTERN/
# PRODUCTION_PATTERN are left blank by default (DevLake then has no GitHub
# signal for Deployment Frequency/Change Failure Rate on these repos; the
# demo dashboard's DORA panels are populated from seeded webhook events
# instead -- see docs/dora-metrics.md). Point these at a real application
# repo's workflow/environment names if you connect one.
: "${DEPLOYMENT_PATTERN:=}"
: "${PRODUCTION_PATTERN:=}"

REPOS=("playwright-agentic" "k6-agentic" "backend-agentic" "KPI-Dashboard")
CONN_NAME="autom8ion-github"

if [[ -z "$GITHUB_TOKEN" ]]; then
    echo "GITHUB_TOKEN not set -- skipping DevLake GitHub connection setup."
    echo "The demo will still work: scripts/seed/generate_sample_data.py pushes"
    echo "synthetic deployments/incidents/PRs straight into DevLake via its"
    echo "webhook plugin, independent of a real GitHub connection."
    exit 0
fi

echo "Waiting for DevLake API..."
until curl -sf "$DEVLAKE_API_URL/ping" >/dev/null 2>&1; do sleep 2; done

echo "Looking for an existing '$CONN_NAME' GitHub connection..."
existing_id=$(curl -sf "$DEVLAKE_API_URL/plugins/github/connections" \
    | python3 -c "import json,sys; conns=json.load(sys.stdin); print(next((c['id'] for c in conns if c['name']=='$CONN_NAME'), ''))")

if [[ -n "$existing_id" ]]; then
    connection_id="$existing_id"
    echo "Reusing connection id=$connection_id"
else
    echo "Creating GitHub connection..."
    connection_id=$(curl -sf -X POST "$DEVLAKE_API_URL/plugins/github/connections" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"$CONN_NAME\", \"endpoint\": \"https://api.github.com/\", \"authMethod\": \"AccessToken\", \"token\": \"$GITHUB_TOKEN\", \"enableGraphql\": true}" \
        | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
    echo "Created connection id=$connection_id"
fi

echo "Creating/reusing 'qa-automation-dora' scope config..."
existing_sc_id=$(curl -sf "$DEVLAKE_API_URL/plugins/github/connections/$connection_id/scope-configs" \
    | python3 -c "import json,sys; scs=json.load(sys.stdin); print(next((s['id'] for s in scs if s['name']=='qa-automation-dora'), ''))" 2>/dev/null || echo "")
if [[ -n "$existing_sc_id" ]]; then
    scope_config_id="$existing_sc_id"
else
    scope_config_id=$(curl -sf -X POST "$DEVLAKE_API_URL/plugins/github/connections/$connection_id/scope-configs" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"qa-automation-dora\", \"issueTypeBug\": \"bug\", \"issueTypeIncident\": \"incident\", \"issueTypeRequirement\": \"enhancement\", \"deploymentPattern\": \"$DEPLOYMENT_PATTERN\", \"productionPattern\": \"$PRODUCTION_PATTERN\"}" \
        | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
fi
echo "Scope config id=$scope_config_id (bug='bug', incident='incident' issue-label mapping)"

echo "Adding repo scopes: ${REPOS[*]}"
scope_json=$(python3 -c "
import json
repos = '${REPOS[*]}'.split()
print(json.dumps({'data': [{'fullName': f'$GITHUB_ORG/{r}', 'scopeConfigId': $scope_config_id} for r in repos]}))
")
curl -sf -X PUT "$DEVLAKE_API_URL/plugins/github/connections/$connection_id/scopes" \
    -H "Content-Type: application/json" \
    -d "$scope_json" >/dev/null

echo "GitHub connection '$CONN_NAME' (id=$connection_id) is configured with ${#REPOS[@]} repo scopes."

if [[ -n "$JIRA_URL" ]]; then
    echo "Creating Jira connection (JIRA_URL is set)..."
    curl -sf -X POST "$DEVLAKE_API_URL/plugins/jira/connections" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"autom8ion-jira\", \"endpoint\": \"${JIRA_URL%/}/rest/\", \"authMethod\": \"AccessToken\", \"username\": \"$JIRA_EMAIL\", \"password\": \"$JIRA_API_TOKEN\"}" \
        >/dev/null
    echo "Jira connection created -- add its board(s) as scopes in the Config UI (Connections -> autom8ion-jira -> Add Data Scope)."
else
    echo "JIRA_URL not set -- Jira stays seeded (see scripts/seed/generate_sample_data.py)."
fi

cat <<'EOF'

Next (one-time, ~2 minutes, in the Config UI): http://localhost:4000
  1. Projects -> New Project -> name it "qa-automation".
  2. Add the "autom8ion-github" connection's scopes to the project
     (and "autom8ion-jira" if you configured one).
  3. Save, then click "Collect Data Now" to run the first blueprint.
This is scripted-connections + UI-driven-project/blueprint by design --
see ARCHITECTURE.md "Why the last step is manual".
EOF
