"""FastAPI service: JSON API over the reporting schema + the dashboard UI.

    uvicorn app.main:app --reload
"""
from __future__ import annotations

import csv
import io
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text

from etl import __version__
from etl.config import get_settings
from etl.db import get_engine, init_db
from etl.pipeline import PipelineBusyError, pending_files, run_pipeline
from etl.rules import CUSTOMER_RULES, ORDER_RULES, PRODUCT_RULES

from .mock_api import router as mock_router

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("app")
RULE_COLUMNS = {r.name: r.column for r in CUSTOMER_RULES + ORDER_RULES + PRODUCT_RULES}

_run_lock = threading.Lock()


def engine():
    return get_engine(get_settings().database_url)


def rows(sql: str, **params) -> list[dict]:
    with engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def one(sql: str, **params) -> dict | None:
    r = rows(sql, **params)
    return r[0] if r else None


# -----------------------------------------------------------------------------
# Lifecycle: create schema and (optionally) seed demo history on first boot
# -----------------------------------------------------------------------------
def _bootstrap_demo(leave: int) -> None:
    settings = get_settings()
    for _ in range(60):  # wait until our own mock API answers so runs use the API path
        try:
            httpx.get(f"{settings.api_base_url}/fx-rates", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.5)
    with _run_lock:
        todo = max(len(pending_files(engine(), settings)) - leave, 0)
        for _ in range(todo):
            try:
                run_pipeline(engine(), settings, triggered_by="demo", max_files=1)
            except Exception:  # noqa: BLE001
                log.exception("demo bootstrap run failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db(engine())
    if os.getenv("DEMO_BOOTSTRAP", "false").lower() in ("1", "true", "yes"):
        if not one("SELECT 1 AS x FROM etl.pipeline_runs LIMIT 1"):
            threading.Thread(target=_bootstrap_demo, args=(int(os.getenv("DEMO_LEAVE_PENDING", "2")),),
                             daemon=True).start()
    yield


app = FastAPI(title="Reporting ETL", version=__version__, lifespan=lifespan,
              description="Pipeline runs, data quality and reporting over the PostgreSQL star schema.")
app.include_router(mock_router)


# -----------------------------------------------------------------------------
# Filters shared by reporting endpoints
# -----------------------------------------------------------------------------
def _where(start: date | None, end: date | None, region: str | None, alias: str = "") -> tuple[str, dict]:
    a = f"{alias}." if alias else ""
    clauses, params = ["TRUE"], {}
    if start:
        clauses.append(f"{a}order_date >= :start")
        params["start"] = start
    if end:
        clauses.append(f"{a}order_date <= :end")
        params["end"] = end
    if region:
        clauses.append(f"{a}region = :region")
        params["region"] = region
    return " AND ".join(clauses), params


def _kpis(start, end, region) -> dict:
    where, p = _where(start, end, region)
    return one(f"""
        SELECT COALESCE(ROUND(SUM(revenue_usd), 2), 0)::float AS revenue,
               COUNT(*) AS orders,
               COALESCE(ROUND(SUM(revenue_usd) / NULLIF(COUNT(*), 0), 2), 0)::float AS aov,
               COUNT(DISTINCT customer_id) AS customers,
               COALESCE(SUM(quantity), 0) AS units
        FROM reporting.v_sales WHERE {where}""", **p)


# -----------------------------------------------------------------------------
# Reporting
# -----------------------------------------------------------------------------
@app.get("/api/meta", tags=["reporting"])
def meta():
    rng = one("SELECT MIN(order_date) AS min_date, MAX(order_date) AS max_date FROM reporting.fact_orders")
    regions = [r["region"] for r in rows("SELECT DISTINCT region FROM reporting.dim_customers ORDER BY 1")]
    last = one("""SELECT run_id, status, finished_at, started_at FROM etl.pipeline_runs
                  ORDER BY run_id DESC LIMIT 1""")
    return {"version": __version__, "regions": regions, **(rng or {}), "last_run": last}


@app.get("/api/overview", tags=["reporting"])
def overview(start: date | None = None, end: date | None = None, region: str | None = None):
    current = _kpis(start, end, region)
    previous = None
    if start and end:
        span = end - start
        prev_end = start.fromordinal(start.toordinal() - 1)
        prev_start = prev_end.fromordinal(prev_end.toordinal() - span.days)
        previous = _kpis(prev_start, prev_end, region)
        if not previous["orders"]:
            previous = None
    where, p = _where(start, end, region)
    flagged = one(f"""SELECT COUNT(*) FILTER (WHERE is_flagged) AS flagged, COUNT(*) AS total
                      FROM (SELECT f.is_flagged, f.order_date, c.region FROM reporting.fact_orders f
                            JOIN reporting.dim_customers c USING (customer_id)) x
                      WHERE {where}""", **p)
    return {"current": current, "previous": previous, "flagged": flagged}


@app.get("/api/sales/monthly", tags=["reporting"])
def sales_monthly(start: date | None = None, end: date | None = None, region: str | None = None):
    where, p = _where(start, end, region)
    return rows(f"""
        SELECT to_char(order_month, 'YYYY-MM') AS month, ROUND(SUM(revenue_usd), 2)::float AS revenue,
               COUNT(*) AS orders, ROUND(SUM(revenue_usd) / COUNT(*), 2)::float AS aov
        FROM reporting.v_sales WHERE {where} GROUP BY order_month ORDER BY order_month""", **p)


@app.get("/api/sales/by-category", tags=["reporting"])
def sales_by_category(start: date | None = None, end: date | None = None, region: str | None = None):
    where, p = _where(start, end, region)
    return rows(f"""SELECT category, ROUND(SUM(revenue_usd), 2)::float AS revenue, COUNT(*) AS orders
                    FROM reporting.v_sales WHERE {where} GROUP BY category ORDER BY revenue DESC""", **p)


@app.get("/api/sales/by-region", tags=["reporting"])
def sales_by_region(start: date | None = None, end: date | None = None):
    where, p = _where(start, end, None)
    return rows(f"""SELECT region, ROUND(SUM(revenue_usd), 2)::float AS revenue, COUNT(*) AS orders,
                           COUNT(DISTINCT customer_id) AS customers
                    FROM reporting.v_sales WHERE {where} GROUP BY region ORDER BY revenue DESC""", **p)


@app.get("/api/sales/by-channel", tags=["reporting"])
def sales_by_channel(start: date | None = None, end: date | None = None, region: str | None = None):
    where, p = _where(start, end, region)
    return rows(f"""SELECT channel, ROUND(SUM(revenue_usd), 2)::float AS revenue, COUNT(*) AS orders
                    FROM reporting.v_sales WHERE {where} GROUP BY channel ORDER BY revenue DESC""", **p)


@app.get("/api/sales/top-products", tags=["reporting"])
def top_products(start: date | None = None, end: date | None = None, region: str | None = None,
                 limit: int = Query(8, ge=1, le=50)):
    where, p = _where(start, end, region)
    return rows(f"""SELECT product_id, product_name, category, SUM(quantity) AS units,
                           ROUND(SUM(revenue_usd), 2)::float AS revenue
                    FROM reporting.v_sales WHERE {where}
                    GROUP BY product_id, product_name, category ORDER BY revenue DESC LIMIT :limit""",
                limit=limit, **p)


# -----------------------------------------------------------------------------
# Pipeline runs
# -----------------------------------------------------------------------------
RUN_COLS = """run_id, started_at, finished_at, status, triggered_by, full_refresh, files_processed,
              api_source, rows_extracted, rows_loaded, rows_rejected, rows_warned, stage_durations,
              error_message, EXTRACT(EPOCH FROM (COALESCE(finished_at, now()) - started_at))::float AS duration_s"""


@app.get("/api/runs", tags=["pipeline"])
def list_runs(limit: int = Query(50, ge=1, le=500)):
    return rows(f"SELECT {RUN_COLS} FROM etl.pipeline_runs ORDER BY run_id DESC LIMIT :limit", limit=limit)


@app.get("/api/runs/{run_id}", tags=["pipeline"])
def get_run(run_id: int):
    run = one(f"SELECT {RUN_COLS}, log FROM etl.pipeline_runs WHERE run_id = :id", id=run_id)
    if not run:
        raise HTTPException(404, "run not found")
    run["rules"] = rows("""SELECT dataset, rule_name, description, severity, column_name, rows_checked,
                                  rows_failed FROM etl.rule_results WHERE run_id = :id
                           ORDER BY rows_failed DESC, dataset, rule_name""", id=run_id)
    return run


class RunRequest(BaseModel):
    full_refresh: bool = False


def _run_in_background(full_refresh: bool) -> None:
    try:
        run_pipeline(engine(), get_settings(), triggered_by="dashboard", full_refresh=full_refresh)
    except PipelineBusyError:
        log.warning("pipeline busy")
    except Exception:  # noqa: BLE001 - failure is recorded on the run row
        log.exception("pipeline run failed")
    finally:
        _run_lock.release()


@app.post("/api/runs", status_code=202, tags=["pipeline"])
def trigger_run(req: RunRequest | None = None):
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(409, "A pipeline run is already in progress")
    threading.Thread(target=_run_in_background, args=((req or RunRequest()).full_refresh,), daemon=True).start()
    return {"accepted": True}


@app.get("/api/pipeline/status", tags=["pipeline"])
def pipeline_status():
    totals = one("""SELECT COUNT(*) AS runs,
                           COUNT(*) FILTER (WHERE status = 'success') AS succeeded,
                           COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                           COALESCE(AVG(EXTRACT(EPOCH FROM finished_at - started_at))
                                    FILTER (WHERE status = 'success'), 0)::float AS avg_duration_s,
                           COALESCE(SUM(rows_loaded), 0) AS rows_loaded
                    FROM etl.pipeline_runs""")
    running = one("SELECT run_id, started_at FROM etl.pipeline_runs WHERE status = 'running' "
                  "ORDER BY run_id DESC LIMIT 1")
    files = rows("""SELECT file_name, row_count, run_id, processed_at FROM etl.processed_files
                    ORDER BY file_name""")
    return {"pending_files": pending_files(engine()), "processed_files": files,
            "running": running or (None if not _run_lock.locked() else {"run_id": None}), **totals}


# -----------------------------------------------------------------------------
# Data quality
# -----------------------------------------------------------------------------
@app.get("/api/quality/trend", tags=["quality"])
def quality_trend():
    return rows("""SELECT run_id, started_at, rows_extracted, rows_rejected, rows_warned,
                          pass_rate_pct::float AS pass_rate
                   FROM etl.v_run_quality WHERE status = 'success' ORDER BY run_id""")


@app.get("/api/quality/rules", tags=["quality"])
def quality_rules(run_id: int | None = None):
    """Rule results for one run, or aggregated over all runs when run_id is omitted."""
    if run_id:
        return rows("""SELECT dataset, rule_name, description, severity, column_name,
                              rows_checked, rows_failed FROM etl.rule_results WHERE run_id = :id
                       ORDER BY rows_failed DESC, dataset, rule_name""", id=run_id)
    return rows("""SELECT dataset, rule_name, MAX(description) AS description, MAX(severity) AS severity,
                          MAX(column_name) AS column_name, SUM(rows_checked)::int AS rows_checked,
                          SUM(rows_failed)::int AS rows_failed
                   FROM etl.rule_results GROUP BY dataset, rule_name
                   ORDER BY rows_failed DESC, dataset, rule_name""")


def _issue_filter(run_id, dataset, rule, severity, q) -> tuple[str, dict]:
    clauses, p = ["TRUE"], {}
    if run_id:
        clauses.append("run_id = :run_id"); p["run_id"] = run_id
    if dataset:
        clauses.append("dataset = :dataset"); p["dataset"] = dataset
    if rule:
        clauses.append(":rule = ANY(reasons)"); p["rule"] = rule
    if severity:
        clauses.append("severity = :severity"); p["severity"] = severity
    if q:
        clauses.append("record::text ILIKE :q"); p["q"] = f"%{q}%"
    return " AND ".join(clauses), p


@app.get("/api/quality/issues", tags=["quality"])
def quality_issues(run_id: int | None = None, dataset: str | None = None, rule: str | None = None,
                   severity: str | None = None, q: str | None = None,
                   limit: int = Query(25, ge=1, le=500), offset: int = Query(0, ge=0)):
    where, p = _issue_filter(run_id, dataset, rule, severity, q)
    total = one(f"SELECT COUNT(*) AS n FROM etl.row_issues WHERE {where}", **p)["n"]
    items = rows(f"""SELECT issue_id, run_id, dataset, source_file, source_row, severity, reasons, record
                     FROM etl.row_issues WHERE {where}
                     ORDER BY run_id DESC, severity, issue_id DESC LIMIT :limit OFFSET :offset""",
                 limit=limit, offset=offset, **p)
    for it in items:
        it["columns"] = sorted({RULE_COLUMNS.get(r) for r in it["reasons"]} - {None})
    return {"total": total, "items": items}


@app.get("/api/quality/issues.csv", tags=["quality"])
def quality_issues_csv(run_id: int | None = None, dataset: str | None = None, rule: str | None = None,
                       severity: str | None = None, q: str | None = None):
    where, p = _issue_filter(run_id, dataset, rule, severity, q)
    items = rows(f"""SELECT run_id, dataset, source_file, source_row, severity, reasons, record
                     FROM etl.row_issues WHERE {where} ORDER BY issue_id""", **p)
    keys = sorted({k for it in items for k in it["record"]})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["run_id", "dataset", "source_file", "source_row", "severity", "reasons", *keys])
    for it in items:
        w.writerow([it["run_id"], it["dataset"], it["source_file"], it["source_row"], it["severity"],
                    ";".join(it["reasons"]), *[it["record"].get(k, "") for k in keys]])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=row_issues.csv"})


# -----------------------------------------------------------------------------
# Data model
# -----------------------------------------------------------------------------
@app.get("/api/model", tags=["model"])
def model():
    objs = rows("""SELECT table_schema AS schema, table_name AS name,
                          CASE WHEN table_type = 'VIEW' THEN 'view' ELSE 'table' END AS kind
                   FROM information_schema.tables WHERE table_schema IN ('reporting', 'etl')
                   ORDER BY table_schema DESC, table_type, table_name""")
    cols = rows("""SELECT table_schema AS schema, table_name AS name, column_name, data_type
                   FROM information_schema.columns WHERE table_schema IN ('reporting', 'etl')
                   ORDER BY ordinal_position""")
    for o in objs:
        o["columns"] = [{"name": c["column_name"], "type": c["data_type"]}
                        for c in cols if c["schema"] == o["schema"] and c["name"] == o["name"]]
        o["rows"] = one(f'SELECT COUNT(*) AS n FROM "{o["schema"]}"."{o["name"]}"')["n"]
    return objs


@app.get("/api/health", tags=["ops"])
def health():
    one("SELECT 1 AS ok")
    return {"status": "ok"}


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
