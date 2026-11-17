"""Load: idempotent upserts into PostgreSQL plus pipeline metadata writes.

Everything for one run is written inside a single transaction, so dashboards
never see a half-loaded batch: either the whole run lands or none of it does.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd
from sqlalchemy import Connection, text

UPSERT_CUSTOMERS = text("""
    INSERT INTO reporting.dim_customers (customer_id, full_name, email, region, country, signup_date, updated_at)
    VALUES (:customer_id, :full_name, :email, :region, :country, :signup_date, now())
    ON CONFLICT (customer_id) DO UPDATE SET
        full_name = EXCLUDED.full_name, email = EXCLUDED.email, region = EXCLUDED.region,
        country = EXCLUDED.country, signup_date = EXCLUDED.signup_date, updated_at = now()
    WHERE (dim_customers.full_name, dim_customers.email, dim_customers.region,
           dim_customers.country, dim_customers.signup_date)
       IS DISTINCT FROM (EXCLUDED.full_name, EXCLUDED.email, EXCLUDED.region,
           EXCLUDED.country, EXCLUDED.signup_date)
""")

UPSERT_PRODUCTS = text("""
    INSERT INTO reporting.dim_products (product_id, product_name, category, list_price_usd, updated_at)
    VALUES (:product_id, :product_name, :category, :list_price_usd, now())
    ON CONFLICT (product_id) DO UPDATE SET
        product_name = EXCLUDED.product_name, category = EXCLUDED.category,
        list_price_usd = EXCLUDED.list_price_usd, updated_at = now()
    WHERE (dim_products.product_name, dim_products.category, dim_products.list_price_usd)
       IS DISTINCT FROM (EXCLUDED.product_name, EXCLUDED.category, EXCLUDED.list_price_usd)
""")

UPSERT_ORDERS = text("""
    INSERT INTO reporting.fact_orders (order_id, order_date, customer_id, product_id, quantity, unit_price,
        currency, fx_rate, discount, revenue_usd, status, channel, is_flagged, run_id, source_file, loaded_at)
    VALUES (:order_id, :order_date, :customer_id, :product_id, :quantity, :unit_price, :currency, :fx_rate,
        :discount, :revenue_usd, :status, :channel, :is_flagged, :run_id, :source_file, now())
    ON CONFLICT (order_id) DO UPDATE SET
        order_date = EXCLUDED.order_date, customer_id = EXCLUDED.customer_id, product_id = EXCLUDED.product_id,
        quantity = EXCLUDED.quantity, unit_price = EXCLUDED.unit_price, currency = EXCLUDED.currency,
        fx_rate = EXCLUDED.fx_rate, discount = EXCLUDED.discount, revenue_usd = EXCLUDED.revenue_usd,
        status = EXCLUDED.status, channel = EXCLUDED.channel, is_flagged = EXCLUDED.is_flagged,
        run_id = EXCLUDED.run_id, source_file = EXCLUDED.source_file, loaded_at = now()
""")

INSERT_RULE_RESULT = text("""
    INSERT INTO etl.rule_results (run_id, dataset, rule_name, description, severity, column_name,
        rows_checked, rows_failed)
    VALUES (:run_id, :dataset, :rule_name, :description, :severity, :column_name, :rows_checked, :rows_failed)
""")

INSERT_ISSUE = text("""
    INSERT INTO etl.row_issues (run_id, dataset, source_file, source_row, severity, reasons, record)
    VALUES (:run_id, :dataset, :source_file, :source_row, :severity, :reasons, CAST(:record AS jsonb))
""")

UPSERT_FILE = text("""
    INSERT INTO etl.processed_files (file_name, checksum, row_count, run_id, processed_at)
    VALUES (:file_name, :checksum, :row_count, :run_id, now())
    ON CONFLICT (file_name) DO UPDATE SET checksum = EXCLUDED.checksum, row_count = EXCLUDED.row_count,
        run_id = EXCLUDED.run_id, processed_at = now()
""")


def _py(v):
    """Convert pandas/numpy scalars into plain Python values the driver understands."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.date()
    return v


def records(df: pd.DataFrame, columns: list[str]) -> list[dict]:
    return [{c: _py(v) for c, v in zip(columns, row)} for row in df[columns].itertuples(index=False, name=None)]


def _json_default(v):
    if isinstance(v, (date, datetime, pd.Timestamp)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return str(v)


def upsert_customers(conn: Connection, df: pd.DataFrame) -> int:
    rows = records(df, ["customer_id", "full_name", "email", "region", "country", "signup_date"])
    if rows:
        conn.execute(UPSERT_CUSTOMERS, rows)
    return len(rows)


def upsert_products(conn: Connection, df: pd.DataFrame) -> int:
    rows = records(df, ["product_id", "product_name", "category", "list_price_usd"])
    if rows:
        conn.execute(UPSERT_PRODUCTS, rows)
    return len(rows)


def upsert_orders(conn: Connection, df: pd.DataFrame, run_id: int) -> int:
    if df.empty:
        return 0
    df = df.assign(run_id=run_id, is_flagged=df["_flagged"].astype(bool), source_file=df["_source_file"])
    cols = ["order_id", "order_date", "customer_id", "product_id", "quantity", "unit_price", "currency",
            "fx_rate", "discount", "revenue_usd", "status", "channel", "is_flagged", "run_id", "source_file"]
    rows = records(df, cols)
    conn.execute(UPSERT_ORDERS, rows)
    return len(rows)


def write_rule_results(conn: Connection, run_id: int, rule_records: list[dict]) -> None:
    if rule_records:
        conn.execute(INSERT_RULE_RESULT, [{**r, "run_id": run_id} for r in rule_records])


def write_issues(conn: Connection, run_id: int, dataset: str, df: pd.DataFrame, raw: pd.DataFrame,
                 severity: str) -> int:
    """Persist rejected/warned rows with their original, untouched source values for replay.

    ``df`` holds the cleaned rows (with ``_reasons``); ``raw`` is the extract they came from,
    sharing the same index.
    """
    if df.empty:
        return 0
    raw_columns = [c for c in raw.columns if not c.startswith("_")]
    rows = []
    for idx, r in df.iterrows():
        record = {c: _py(raw.at[idx, c]) for c in raw_columns}
        rows.append({
            "run_id": run_id, "dataset": dataset, "source_file": str(r["_source_file"]),
            "source_row": int(r["_source_row"]), "severity": severity, "reasons": list(r["_reasons"]),
            "record": json.dumps(record, default=_json_default),
        })
    conn.execute(INSERT_ISSUE, rows)
    return len(rows)


def mark_files_processed(conn: Connection, run_id: int, files: list[dict]) -> None:
    if files:
        conn.execute(UPSERT_FILE, [{**f, "run_id": run_id} for f in files])
