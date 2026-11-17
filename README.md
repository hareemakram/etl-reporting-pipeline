# ETL Pipeline for Reporting Data

**Python (pandas) · SQL · PostgreSQL · FastAPI**

This pipeline pulls raw sales data from CSV exports and a REST API, checks every row against 29 validation rules and loads the clean result into a PostgreSQL star schema. That schema is the source for the reporting dashboards. A web UI built into the project shows the reports, each pipeline run, data-quality results, and every rejected row with the reason it was rejected.

![Dashboard](docs/screenshots/dashboard.png)

---

## Highlights

| | |
|---|---|
| **Extract** | Reads monthly order CSVs, a customer master CSV and a paginated REST API (product catalog + FX rates). Order loads are **incremental**: a file manifest in Postgres tracks files by checksum, so a corrected file is detected and reloaded. The API client retries with exponential backoff. If the API stays down it falls back to the last snapshot, so a flaky upstream never blocks a load. |
| **Transform** | Every column is read as a string, then trimmed, case-normalised and type-coerced with pandas. A bad value becomes `NaN` and is caught by validation. It never crashes the job. Orders are converted to USD net of discount. |
| **Validate** | A small **declarative rule framework** (`etl/validate.py`) with 29 vectorised rules (`etl/rules.py`): not-null, uniqueness, formats, allowed values, date sanity, referential integrity against the customer and product masters, plus *warning* rules for bulk-quantity outliers and price drift. A row that breaks an **error** rule is rejected and quarantined with the list of every rule it broke and its original raw values, ready for replay. A row that breaks only a **warning** rule is loaded with an `is_flagged` marker. |
| **Load** | Idempotent `INSERT … ON CONFLICT` upserts into `reporting.dim_customers`, `dim_products` and `fact_orders`. The data, rule results, rejected rows and file manifest are all written in **one transaction**, so dashboards never see a half-loaded batch. A Postgres advisory lock stops two runs from overlapping. |
| **Serve** | SQL views (`reporting.v_sales`, `v_monthly_revenue`, `v_revenue_by_region`, …) are the clean source for the bundled dashboard and for any BI tool (Metabase, Superset, Power BI, Tableau). |
| **Observe** | Each run records its status, row counts, per-stage timings and a structured log in `etl.pipeline_runs`. The UI shows all of this. |

## Quick start (Docker)

```bash
cp .env.example .env        # optional, defaults work
docker compose up --build
```

Open **http://localhost:8000**. On first start the app creates the schema and loads Jan–Oct 2024 one month per run, which builds a run history. It leaves **Nov and Dec waiting** so you can go to **Pipeline runs → Run pipeline** and watch a live incremental load. The interactive API docs are at `/docs`.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
make install                # pip install -r requirements-dev.txt
make db                     # Postgres 16 in Docker on :5432 (or point DATABASE_URL at your own)
make demo                   # python -m etl demo   -> 10 runs, 2 files left pending
make serve                  # uvicorn app.main:app --reload
```

CLI:

```bash
python -m etl run                    # load every pending file
python -m etl run --max-files 1      # load the next file only
python -m etl run --full-refresh     # reprocess everything (upserts, no duplicates)
python -m etl status                 # recent runs + pending files
python scripts/generate_sample_data.py --seed 7   # fresh synthetic data
```

## The UI

| Page | What it shows |
|---|---|
| **Dashboard** | Net revenue, orders, AOV and active customers, with change vs the previous period. Also monthly revenue, revenue by region (click a bar to filter), category, top products and channel mix, with filters for quarter and region. |
| **Pipeline runs** | Files waiting to load, a one-click run (or full refresh), success rate, run history with a stage-timing bar for each run, and a detail drawer with rule results and the full run log. |
| **Data quality** | Pass rate per run, failures by rule, the rule catalog, and an explorer for rejected and flagged rows. It shows the raw source values with the failing field highlighted, filters by run, dataset, rule or free text, and exports to CSV. |
| **Data model** | The pipeline flow, plus every table and view live from `information_schema`, with row counts. |

Light and dark themes are both included, and the layout works on phones down to 360 px.

| Pipeline runs | Run detail |
|---|---|
| ![Runs](docs/screenshots/runs.png) | ![Run detail](docs/screenshots/run-detail.png) |
| **Data quality** | **Rejected rows** |
| ![Data quality](docs/screenshots/data-quality.png) | ![Rejected rows](docs/screenshots/rejected-rows.png) |
| **Data model** | **Dark mode** |
| ![Data model](docs/screenshots/data-model.png) | ![Dark](docs/screenshots/dashboard-dark.png) |

## Architecture

```mermaid
flowchart LR
  subgraph Sources
    A[orders_2024_MM.csv]:::src
    B[customers.csv]:::src
    C[REST API<br/>/products · /fx-rates]:::src
  end
  A & B --> E[Extract<br/>pandas, checksum manifest]
  C --> E
  E --> T[Transform<br/>clean · type · normalise]
  T --> V{Validate<br/>29 rules}
  V -- error --> Q[(etl.row_issues<br/>quarantine)]
  V -- valid / warning --> L[Load<br/>upsert, 1 transaction]
  L --> R[(reporting.*<br/>star schema)]
  R --> W[[SQL views]] --> D[Dashboard / BI]
  L --> M[(etl.pipeline_runs<br/>rule_results)]
  classDef src fill:#e8f1fc,stroke:#2a78d6
```

```
reporting.dim_customers ─┐
reporting.dim_products  ─┼─< reporting.fact_orders >── etl.pipeline_runs ──< etl.rule_results
                         │                                              └──< etl.row_issues
                         └── views: v_sales, v_monthly_revenue, v_revenue_by_category,
                                    v_revenue_by_region, v_top_products, v_order_status
```

## Project layout

```
etl/
  extract.py      CSV readers, checksum manifest, resilient API client
  transform.py    cleaning / typing / USD enrichment
  validate.py     declarative rule framework
  rules.py        the rule catalog per dataset
  load.py         upserts and metadata writes
  pipeline.py     orchestration, stage timing, run log, advisory lock
  __main__.py     CLI
sql/
  schema.sql      etl.* and reporting.* tables (idempotent)
  views.sql       reporting views
app/
  main.py         FastAPI: reporting / pipeline / quality / model endpoints
  mock_api.py     stand-in upstream API (pagination + random 503s)
  static/         dashboard UI (vanilla JS + Chart.js, no build step)
data/
  raw/            sample CSVs (8.5k orders, ~4–7% deliberately dirty)
  fixtures/       API payloads and offline fallback
scripts/generate_sample_data.py
tests/            unit + Postgres integration + API tests
```

## Tests

```bash
make test        # needs TEST_DATABASE_URL; DB tests are skipped without it
make lint
```

There are 17 tests. Unit tests cover cleaning, each validation rule, and API pagination, retry and fallback. Integration tests run the real pipeline against PostgreSQL and check incremental loads, idempotent reloads of a corrected file, full refresh, and that a failed run is recorded and rolled back. API tests run against a freshly loaded database. CI (`.github/workflows/ci.yml`) runs ruff and pytest against a Postgres 16 service container.

## Sample data

`scripts/generate_sample_data.py` creates a year of retail orders across 4 regions, 9 currencies and 36 products. It includes a holiday peak and seeded defects: missing keys, negative quantities, impossible dates, unknown products and customers, unsupported currencies, out-of-range discounts, duplicate IDs, malformed emails, bulk outliers and price drift. The defect rate drifts from month to month (a "bad upstream release" in May–June), so the data-quality trend has something to show.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://etl:etl@localhost:5432/reporting` | target database |
| `API_BASE_URL` | `http://localhost:8000/mock-api` | product/FX API |
| `API_MAX_RETRIES` | `3` | retries with exponential backoff |
| `MOCK_API_FAILURE_RATE` | `0.15` | share of mock-API requests that return 503 |
| `PRICE_DRIFT_THRESHOLD` | `0.35` | price-drift warning threshold |
| `DEMO_BOOTSTRAP` / `DEMO_LEAVE_PENDING` | `false` / `2` | seed run history on first start |
