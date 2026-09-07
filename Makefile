# Smart CNC Factory MES Copilot — developer tasks
# Day 2: database lifecycle. Backend/frontend targets arrive on Days 3 and 8.

-include .env

POSTGRES_USER    ?= mes
POSTGRES_DB      ?= mes
FACTORY_TIMEZONE ?= Asia/Tokyo

PSQL = docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
       -v ON_ERROR_STOP=1 -v factory_tz=$(FACTORY_TIMEZONE)

.PHONY: help env db-up db-down db-reset db-schema db-seed db-verify db-rehearse db-shell

help:
	@echo "make env         copy .env.example to .env (once)"
	@echo "make db-up       start PostgreSQL (auto-runs schema, seed and verify on first start)"
	@echo "make db-reset    destroy the volume and rebuild the factory from scratch"
	@echo "make db-schema   (re)apply db/schema.sql"
	@echo "make db-seed     (re)apply db/seed.sql   — rebases the factory onto the current ISO week"
	@echo "make db-verify   run the 20 data assertions in db/verify.sql"
	@echo "make db-rehearse DATE=2026-09-11   seed and verify as if today were DATE"
	@echo "make db-shell    open psql"
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
