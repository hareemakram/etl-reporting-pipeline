"""End-to-end tests against a real PostgreSQL (set TEST_DATABASE_URL)."""
import pytest
from sqlalchemy import text

from etl.pipeline import run_pipeline

from .conftest import TODAY


def scalar(engine, sql):
    with engine.connect() as c:
        return c.execute(text(sql)).scalar()


def test_full_run_loads_clean_rows_and_quarantines_bad_ones(engine, settings):
    s = run_pipeline(engine, settings, today=TODAY)
    assert s.status == "success"
    assert s.files == ["orders_2024_01.csv"]
    assert scalar(engine, "SELECT COUNT(*) FROM reporting.dim_customers") == 2
    assert scalar(engine, "SELECT COUNT(*) FROM reporting.dim_products") == 2
    assert scalar(engine, "SELECT string_agg(order_id, ',' ORDER BY order_id) FROM reporting.fact_orders") == "ORD-1,ORD-2,ORD-8"
    assert scalar(engine, "SELECT is_flagged FROM reporting.fact_orders WHERE order_id = 'ORD-8'") is True
    # EUR -> USD conversion after discount
    assert float(scalar(engine, "SELECT revenue_usd FROM reporting.fact_orders WHERE order_id = 'ORD-1'")) == 180.0
    # rejected rows keep raw source values for replay
    rec = scalar(engine, "SELECT record FROM etl.row_issues WHERE 'quantity_positive_int' = ANY(reasons)")
    assert rec["quantity"] == "-3"
    assert s.rows_rejected == scalar(engine, "SELECT COUNT(*) FROM etl.row_issues WHERE severity = 'error'") == 10
    with engine.connect() as c:
        run = dict(c.execute(text("SELECT * FROM etl.pipeline_runs")).mappings().one())
    assert run["status"] == "success" and set(run["stage_durations"]) == {"extract", "transform", "validate", "load"}
    assert run["api_source"] == "fixture"


def test_incremental_and_idempotent(engine, settings, raw_dir):
    run_pipeline(engine, settings, today=TODAY)
    second = run_pipeline(engine, settings, today=TODAY)
    assert second.files == []                                    # nothing new to load
    assert scalar(engine, "SELECT COUNT(*) FROM reporting.fact_orders") == 3
    # a corrected file is re-detected by checksum and upserted, not duplicated
    f = raw_dir / "orders" / "orders_2024_01.csv"
    f.write_text(f.read_text().replace("ORD-6,2024-01-08,C00002,P0002,-3", "ORD-6,2024-01-08,C00002,P0002,3"))
    third = run_pipeline(engine, settings, today=TODAY)
    assert third.files == ["orders_2024_01.csv"]
    assert scalar(engine, "SELECT COUNT(*) FROM reporting.fact_orders") == 4
    full = run_pipeline(engine, settings, today=TODAY, full_refresh=True)
    assert full.files == ["orders_2024_01.csv"]
    assert scalar(engine, "SELECT COUNT(*) FROM reporting.fact_orders") == 4


def test_failed_run_is_recorded_and_rolled_back(engine, settings, raw_dir):
    (raw_dir / "customers.csv").write_text("not,the,right,header\n1,2,3,4\n")
    with pytest.raises(KeyError):
        run_pipeline(engine, settings, today=TODAY)
    assert scalar(engine, "SELECT status FROM etl.pipeline_runs") == "failed"
    assert "customer_id" in scalar(engine, "SELECT error_message FROM etl.pipeline_runs")
    assert scalar(engine, "SELECT COUNT(*) FROM reporting.fact_orders") == 0
    assert scalar(engine, "SELECT COUNT(*) FROM etl.processed_files") == 0
