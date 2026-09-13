# Smart CNC Factory MES Copilot — developer tasks
# Database, backend and web interface.

-include .env

POSTGRES_USER    ?= mes
POSTGRES_DB      ?= mes
FACTORY_TIMEZONE ?= Asia/Tokyo

MES_RO_PASSWORD ?= mes_ro

PSQL = docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
       -v ON_ERROR_STOP=1 -v factory_tz=$(FACTORY_TIMEZONE) -v ro_password=$(MES_RO_PASSWORD)

.PHONY: help env db-up db-down db-reset db-schema db-seed db-verify db-rehearse db-shell \
        backend-install backend-dev test lint llm-pull llm-check up down logs ps \
        web-install web-dev web-build web-test web-lint factory-timezone

help:
	@echo "make env         copy .env.example to .env (once)"
	@echo "make db-up       start PostgreSQL (auto-runs schema, seed and verify on first start)"
	@echo "make db-reset    destroy the volume and rebuild the factory from scratch"
	@echo "make db-schema   (re)apply db/schema.sql"
	@echo "make db-seed     (re)apply db/seed.sql   — rebases the factory onto the current ISO week"
	@echo "make db-verify   run the 20 data assertions in db/verify.sql"
	@echo "make db-rehearse DATE=2026-09-11   seed and verify as if today were DATE"
	@echo "make db-shell    open psql"
	@echo "make factory-timezone ZONE=Asia/Shanghai   move the factory to another time zone"
	@echo ""
	@echo "make up          start the whole stack (postgres + backend)"
	@echo "make down        stop the stack"
	@echo "make logs        follow backend logs"
	@echo "make backend-install   create backend/.venv and install dependencies"
	@echo "make backend-dev       run the API locally with reload on http://localhost:8000"
	@echo "make test              run the backend test suite"
	@echo "make lint              ruff check + format check"
	@echo ""
	@echo "make web-install       install the frontend dependencies"
	@echo "make web-dev           run the web interface on http://localhost:3000 with reload"
	@echo "make web-build         production build of the web interface"
	@echo "make web-test          frontend unit tests"
	@echo "make web-lint          eslint + tsc --noEmit"
	@echo "make llm-pull          download the configured model into the local model server"
	@echo "make llm-check         check the local model is reliable enough to drive the agent"
	@echo ""
	@echo "factory timezone: $(FACTORY_TIMEZONE)   (set FACTORY_TIMEZONE in .env)"

env:
	@test -f .env || (cp .env.example .env && echo "created .env")

db-up: env
	docker compose up -d postgres
	@echo "waiting for postgres..."
	@until docker compose exec -T postgres pg_isready -U $(POSTGRES_USER) -d $(POSTGRES_DB) >/dev/null 2>&1; do sleep 1; done
	@echo "ready"

db-down:
	docker compose down

db-reset:
	docker compose down -v
	$(MAKE) db-up

db-schema:
	$(PSQL) < db/schema.sql

db-seed:
	$(PSQL) < db/seed.sql

db-verify:
	$(PSQL) < db/verify.sql

db-rehearse:
	@test -n "$(DATE)" || (echo "usage: make db-rehearse DATE=2026-09-11"; exit 1)
	$(PSQL) -v demo_today="DATE '$(DATE)'" < db/seed.sql
	$(PSQL) -v demo_today="DATE '$(DATE)'" < db/verify.sql

db-shell:
	docker compose exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

# Move the factory to another time zone. This is a deployment decision, not a
# viewer preference: it changes what "today" and "this week" mean for every
# question, so it is done here, deliberately, rather than from the web page.
# Viewers anywhere already see times in their own zone (see docs/11 §Time zones).
#
# It validates the name, writes FACTORY_TIMEZONE to .env, rebases the dataset
# onto the factory's new "today" (which also sets the database's time zone), and
# recreates the backend so it reads the new value.
factory-timezone:
	@test -n "$(ZONE)" || (echo "usage: make factory-timezone ZONE=Asia/Shanghai"; exit 1)
	@python3 -c "import sys, zoneinfo; zoneinfo.ZoneInfo(sys.argv[1])" "$(ZONE)" 2>/dev/null \
		|| (echo "'$(ZONE)' is not an IANA time zone — use a name such as Asia/Shanghai"; exit 1)
	@if grep -q '^FACTORY_TIMEZONE=' .env; then \
		sed -i 's|^FACTORY_TIMEZONE=.*|FACTORY_TIMEZONE=$(ZONE)|' .env; \
	else echo 'FACTORY_TIMEZONE=$(ZONE)' >> .env; fi
	$(MAKE) db-seed FACTORY_TIMEZONE=$(ZONE)
	docker compose up -d --force-recreate backend
	@echo "factory time zone is now $(ZONE)"

# ---------------------------------------------------------------- backend

VENV   = backend/.venv
PY     = $(VENV)/bin/python
PYTEST = $(VENV)/bin/pytest
RUFF   = $(VENV)/bin/ruff

$(VENV):
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q -e "backend[dev]"

backend-install: $(VENV)
	@echo "backend dependencies installed in $(VENV)"

backend-dev: $(VENV)
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port $(or $(API_PORT),8000)

test: $(VENV)
	cd backend && .venv/bin/pytest -q

llm-pull:
	@test -n "$(LLM_MODEL)" || (echo "LLM_MODEL is not set"; exit 1)
	docker compose exec -T ollama ollama pull $(LLM_MODEL)
	@echo "pulled $(LLM_MODEL)"

llm-check: $(VENV)
	cd backend && .venv/bin/python scripts/check_llm.py $(ARGS)

lint: $(VENV)
	$(RUFF) check backend/app backend/tests
	$(RUFF) format --check backend/app backend/tests

# --------------------------------------------------------------- frontend

WEB = frontend

$(WEB)/node_modules: $(WEB)/package.json
	cd $(WEB) && npm install
	@touch $(WEB)/node_modules

web-install: $(WEB)/node_modules

# The dev server talks to whatever API_PORT the backend is on; inside compose
# the container gets MES_API_URL=http://backend:8000 instead.
web-dev: $(WEB)/node_modules
	cd $(WEB) && MES_API_URL=http://localhost:$(or $(API_PORT),8000) npm run dev

web-build: $(WEB)/node_modules
	cd $(WEB) && npm run build

web-test: $(WEB)/node_modules
	cd $(WEB) && npm test

web-lint: $(WEB)/node_modules
	cd $(WEB) && npm run lint

# ------------------------------------------------------------------ stack

up: env
	docker compose up -d --build
	@echo "Web on http://localhost:$(or $(WEB_PORT),3000)"
	@echo "API on http://localhost:$(or $(API_PORT),8000)/docs"

down:
	docker compose down

logs:
	docker compose logs -f backend

ps:
	docker compose ps
