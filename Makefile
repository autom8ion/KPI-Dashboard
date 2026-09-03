.PHONY: demo up down logs venv bootstrap seed ingest report clean

PYTHON ?= python3
VENV := .venv
VENV_PY := $(VENV)/bin/python

$(VENV)/bin/activate: requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV_PY) -m pip install --quiet --upgrade pip
	$(VENV_PY) -m pip install --quiet -r requirements.txt

venv: $(VENV)/bin/activate

.env:
	cp .env.example .env
	@$(PYTHON) -c "import re, secrets, pathlib; \
		p = pathlib.Path('.env'); \
		p.write_text(re.sub(r'^ENCRYPTION_SECRET=$$', 'ENCRYPTION_SECRET=' + secrets.token_hex(16), p.read_text(), flags=re.M))"
	@echo "Created .env from .env.example (generated a fresh ENCRYPTION_SECRET) -- edit it to add GITHUB_TOKEN for live data, or leave blank for seeded-only."

## One command: bring the stack up, configure DevLake, seed sample data.
demo: .env up bootstrap seed
	@echo ""
	@echo "Grafana:            http://localhost:4000/grafana  (admin/admin on first login)"
	@echo "DevLake config UI:  http://localhost:4000"
	@echo "qa-postgres:        localhost:5433 (qa/qa/qa_metrics)"
	@echo ""
	@echo "Open the 'QA Automation KPIs' and 'DORA Overview' dashboards in Grafana."

up: .env
	docker compose up -d
	@echo "Waiting for DevLake to become healthy..."
	@until docker compose ps devlake --format '{{.Health}}' | grep -q healthy; do sleep 2; done
	@echo "Waiting for qa-postgres to become healthy..."
	@until docker compose ps qa-postgres --format '{{.Health}}' | grep -q healthy; do sleep 2; done

down:
	docker compose down

clean:
	docker compose down -v
	rm -rf $(VENV)

logs:
	docker compose logs -f

bootstrap: .env
	bash devlake/scripts/bootstrap.sh

seed: venv .env
	set -a && . ./.env && set +a && $(VENV_PY) -m scripts.seed.generate_sample_data

## Pull real GitHub Actions test results into qa-postgres (needs GITHUB_TOKEN in .env).
ingest: venv .env
	set -a && . ./.env && set +a && $(VENV_PY) -m qa_collector.run

## Generate the Claude-authored QA KPI report (runs the qa-kpi-report skill headlessly).
report:
	@command -v claude >/dev/null || { echo "Claude Code CLI not found on PATH"; exit 1; }
	set -a && . ./.env && set +a && \
	claude -p "Use the qa-kpi-report skill to generate this week's QA KPI report and write it to reports/." \
		--allowedTools "Read,Write,Bash"
