-- =============================================================================
-- ETL Pipeline for Reporting Data — PostgreSQL schema
--
--   etl.*        pipeline metadata: runs, file manifest, rule results, rejected rows
--   reporting.*  the clean, conformed star schema that dashboards read from
--
-- Every statement is idempotent so the schema can be applied on each start-up.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS etl;
CREATE SCHEMA IF NOT EXISTS reporting;

-- -----------------------------------------------------------------------------
-- Pipeline metadata
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etl.pipeline_runs (
    run_id           BIGSERIAL PRIMARY KEY,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    status           TEXT        NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'success', 'failed')),
    triggered_by     TEXT        NOT NULL DEFAULT 'cli',
    full_refresh     BOOLEAN     NOT NULL DEFAULT FALSE,
    files_processed  TEXT[]      NOT NULL DEFAULT '{}',
    api_source       TEXT,
    rows_extracted   INTEGER     NOT NULL DEFAULT 0,
    rows_loaded      INTEGER     NOT NULL DEFAULT 0,
    rows_rejected    INTEGER     NOT NULL DEFAULT 0,
    rows_warned      INTEGER     NOT NULL DEFAULT 0,
    stage_durations  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    log              JSONB       NOT NULL DEFAULT '[]'::jsonb,
    error_message    TEXT
);

-- Manifest of source files already ingested: makes order loads incremental.
CREATE TABLE IF NOT EXISTS etl.processed_files (
    file_name     TEXT PRIMARY KEY,
    checksum      TEXT        NOT NULL,
    row_count     INTEGER     NOT NULL,
    run_id        BIGINT      NOT NULL REFERENCES etl.pipeline_runs (run_id) ON DELETE CASCADE,
    processed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per (run, dataset, rule): how many rows were checked and how many failed.
CREATE TABLE IF NOT EXISTS etl.rule_results (
    run_id        BIGINT  NOT NULL REFERENCES etl.pipeline_runs (run_id) ON DELETE CASCADE,
    dataset       TEXT    NOT NULL,
    rule_name     TEXT    NOT NULL,
    description   TEXT    NOT NULL,
    severity      TEXT    NOT NULL CHECK (severity IN ('error', 'warning')),
    column_name   TEXT,
    rows_checked  INTEGER NOT NULL,
    rows_failed   INTEGER NOT NULL,
    PRIMARY KEY (run_id, dataset, rule_name)
);

-- Rows that were rejected (severity = error) or loaded with a flag (warning).
-- The original record is kept verbatim as JSONB so it can be fixed and replayed.
CREATE TABLE IF NOT EXISTS etl.row_issues (
    issue_id     BIGSERIAL PRIMARY KEY,
    run_id       BIGINT  NOT NULL REFERENCES etl.pipeline_runs (run_id) ON DELETE CASCADE,
    dataset      TEXT    NOT NULL,
    source_file  TEXT    NOT NULL,
    source_row   INTEGER NOT NULL,
    severity     TEXT    NOT NULL CHECK (severity IN ('error', 'warning')),
    reasons      TEXT[]  NOT NULL,
    record       JSONB   NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_row_issues_run     ON etl.row_issues (run_id);
CREATE INDEX IF NOT EXISTS ix_row_issues_reasons ON etl.row_issues USING GIN (reasons);

-- -----------------------------------------------------------------------------
-- Reporting star schema
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reporting.dim_customers (
    customer_id  TEXT PRIMARY KEY,
    full_name    TEXT NOT NULL,
    email        TEXT NOT NULL,
    region       TEXT NOT NULL,
    country      TEXT NOT NULL,
    signup_date  DATE NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reporting.dim_products (
    product_id      TEXT PRIMARY KEY,
    product_name    TEXT          NOT NULL,
    category        TEXT          NOT NULL,
    list_price_usd  NUMERIC(12,2) NOT NULL CHECK (list_price_usd > 0),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reporting.fact_orders (
    order_id      TEXT PRIMARY KEY,
    order_date    DATE          NOT NULL,
    customer_id   TEXT          NOT NULL REFERENCES reporting.dim_customers (customer_id),
    product_id    TEXT          NOT NULL REFERENCES reporting.dim_products (product_id),
    quantity      INTEGER       NOT NULL CHECK (quantity > 0),
    unit_price    NUMERIC(14,2) NOT NULL CHECK (unit_price > 0),
    currency      CHAR(3)       NOT NULL,
    fx_rate       NUMERIC(14,6) NOT NULL,
    discount      NUMERIC(4,3)  NOT NULL CHECK (discount BETWEEN 0 AND 0.6),
    revenue_usd   NUMERIC(14,2) NOT NULL,
    status        TEXT          NOT NULL,
    channel       TEXT          NOT NULL,
    is_flagged    BOOLEAN       NOT NULL DEFAULT FALSE,
    run_id        BIGINT        NOT NULL REFERENCES etl.pipeline_runs (run_id),
    source_file   TEXT          NOT NULL,
    loaded_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fact_orders_date     ON reporting.fact_orders (order_date);
CREATE INDEX IF NOT EXISTS ix_fact_orders_customer ON reporting.fact_orders (customer_id);
CREATE INDEX IF NOT EXISTS ix_fact_orders_product  ON reporting.fact_orders (product_id);
