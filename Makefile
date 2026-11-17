.PHONY: up down install db data run demo serve test lint reset

DATABASE_URL ?= postgresql+psycopg://etl:etl@localhost:5432/reporting
TEST_DATABASE_URL ?= $(DATABASE_URL)_test
export DATABASE_URL

up:            ## Postgres + app in Docker, demo history seeded -> http://localhost:8000
	docker compose up --build -d
	@echo "Dashboard: http://localhost:8000"

down:
	docker compose down

install:
	pip install -r requirements-dev.txt

db:            ## only Postgres in Docker (for local development)
	docker compose up -d db

data:          ## regenerate the sample CSV/API data
	python scripts/generate_sample_data.py

run:           ## one pipeline run over all pending files
	python -m etl -v run

demo:          ## load all but two months, one run per month
	python -m etl demo

serve:         ## dashboard with hot reload
	uvicorn app.main:app --reload --port 8000

test:
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) pytest

lint:
	ruff check .

reset:         ## wipe pipeline + reporting schemas
	psql "$(subst +psycopg,,$(DATABASE_URL))" -c "DROP SCHEMA IF EXISTS reporting CASCADE; DROP SCHEMA IF EXISTS etl CASCADE;"
