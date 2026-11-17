"""Orchestrates one pipeline run: extract -> clean -> validate -> enrich -> load.

Each run is recorded in ``etl.pipeline_runs`` with per-stage timings, row
counts and a structured log, which is what the dashboard's "Pipeline runs"
and "Data quality" pages are built on.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import Engine, text

from . import extract, load, transform
from .config import Settings, get_settings
from .rules import CUSTOMER_RULES, ORDER_RULES, PRODUCT_RULES
from .validate import ValidationResult, run_rules

logger = logging.getLogger("etl")
ADVISORY_LOCK_ID = 7_301_2024  # one pipeline at a time, across processes


class PipelineBusyError(RuntimeError):
    """Another run currently holds the pipeline lock."""


@dataclass
class RunLog:
    entries: list[dict] = field(default_factory=list)

    def __call__(self, level: str, msg: str) -> None:
        self.entries.append({"ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                             "level": level, "msg": msg})
        getattr(logger, level if level in ("info", "warning", "error") else "info")(msg)


@dataclass
class RunSummary:
    run_id: int
    status: str
    files: list[str]
    rows_extracted: int = 0
    rows_loaded: int = 0
    rows_rejected: int = 0
    rows_warned: int = 0
    stage_durations: dict[str, float] = field(default_factory=dict)
    error: str | None = None


@contextmanager
def _stage(name: str, durations: dict[str, float], log: RunLog):
    log("info", f"▶ {name}")
    t0 = time.perf_counter()
    try:
        yield
    finally:
        durations[name] = round(time.perf_counter() - t0, 3)
        log("info", f"✓ {name} finished in {durations[name]:.2f}s")


@contextmanager
def _pipeline_lock(engine: Engine):
    conn = engine.connect()
    try:
        got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_ID}).scalar()
        if not got:
            raise PipelineBusyError("A pipeline run is already in progress")
        yield
    finally:
        try:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_ID})
        finally:
            conn.close()


def _start_run(engine: Engine, triggered_by: str, full_refresh: bool) -> int:
    with engine.begin() as conn:
        return conn.execute(text(
            "INSERT INTO etl.pipeline_runs (triggered_by, full_refresh) VALUES (:t, :f) RETURNING run_id"),
            {"t": triggered_by, "f": full_refresh}).scalar_one()


def _finish_run(conn_or_engine, s: RunSummary, api_source: str | None, log: RunLog) -> None:
    stmt = text("""
        UPDATE etl.pipeline_runs SET status = :status, finished_at = now(), files_processed = :files,
            api_source = :api, rows_extracted = :ext, rows_loaded = :loaded, rows_rejected = :rej,
            rows_warned = :warn, stage_durations = CAST(:dur AS jsonb), log = CAST(:log AS jsonb),
            error_message = :err
        WHERE run_id = :run_id""")
    params = {"status": s.status, "files": s.files, "api": api_source, "ext": s.rows_extracted,
              "loaded": s.rows_loaded, "rej": s.rows_rejected, "warn": s.rows_warned,
              "dur": json.dumps(s.stage_durations), "log": json.dumps(log.entries), "err": s.error,
              "run_id": s.run_id}
    if isinstance(conn_or_engine, Engine):
        with conn_or_engine.begin() as conn:
            conn.execute(stmt, params)
    else:
        conn_or_engine.execute(stmt, params)


def run_pipeline(engine: Engine, settings: Settings | None = None, *, triggered_by: str = "cli",
                 full_refresh: bool = False, max_files: int | None = None,
                 today: pd.Timestamp | None = None) -> RunSummary:
    settings = settings or get_settings()
    today = today or pd.Timestamp.now().normalize()
    with _pipeline_lock(engine):
        run_id = _start_run(engine, triggered_by, full_refresh)
        log = RunLog()
        summary = RunSummary(run_id=run_id, status="running", files=[])
        api_source = None
        log("info", f"Run #{run_id} started (trigger={triggered_by}, full_refresh={full_refresh})")
        try:
            # ------------------------------------------------------------ extract
            with _stage("extract", summary.stage_durations, log):
                with engine.connect() as conn:
                    processed = {} if full_refresh else dict(conn.execute(
                        text("SELECT file_name, checksum FROM etl.processed_files")).all())
                    existing_customers = set(conn.execute(
                        text("SELECT customer_id FROM reporting.dim_customers")).scalars())
                pending = extract.list_pending_order_files(settings.orders_dir, processed)
                if max_files is not None:
                    pending = pending[:max_files]
                summary.files = [p.name for p in pending]
                raw_orders = extract.read_order_files(pending)
                raw_customers = extract.read_csv(settings.customers_file)
                api = extract.extract_api(settings, log)
                api_source = api.source
                log("info", f"CSV: {len(raw_customers)} customer rows; {len(raw_orders)} order rows "
                            f"from {len(pending)} new file(s){': ' + ', '.join(summary.files) if pending else ''}")

            # ---------------------------------------------------------- transform
            with _stage("transform", summary.stage_durations, log):
                products = transform.clean_products(api.products)
                customers = transform.clean_customers(raw_customers)
                orders = transform.clean_orders(raw_orders) if len(raw_orders) else raw_orders

            # ----------------------------------------------------------- validate
            with _stage("validate", summary.stage_durations, log):
                p_res = run_rules(products, PRODUCT_RULES, "products")
                c_res = run_rules(customers, CUSTOMER_RULES, "customers", {"today": today})
                results: list[tuple[ValidationResult, pd.DataFrame]] = [
                    (p_res, api.products), (c_res, raw_customers)]
                o_res = None
                if len(orders):
                    ctx = {
                        "today": today,
                        "known_customers": set(c_res.valid["customer_id"]) | existing_customers,
                        "known_products": set(p_res.valid["product_id"]),
                        "list_prices": dict(zip(p_res.valid["product_id"], p_res.valid["list_price_usd"])),
                        "fx_rates": api.fx_rates,
                        "price_drift_threshold": settings.price_drift_threshold,
                    }
                    o_res = run_rules(orders, ORDER_RULES, "orders", ctx)
                    results.append((o_res, raw_orders))
                for res, _ in results:
                    failed = {o.rule.name: o.rows_failed for o in res.outcomes if o.rows_failed}
                    log("info" if not len(res.rejected) else "warning",
                        f"{res.dataset}: {len(res.valid)} valid, {len(res.rejected)} rejected, "
                        f"{len(res.warned)} flagged" + (f" — {failed}" if failed else ""))
                enriched = (transform.enrich_orders(o_res.valid, p_res.valid, api.fx_rates)
                            if o_res is not None else None)

            # --------------------------------------------------------------- load
            with engine.begin() as conn:     # one transaction: all-or-nothing
                with _stage("load", summary.stage_durations, log):
                    load.upsert_products(conn, p_res.valid)
                    load.upsert_customers(conn, c_res.valid)
                    n_orders = load.upsert_orders(conn, enriched, run_id) if enriched is not None else 0
                    for res, raw in results:
                        load.write_rule_results(conn, run_id, res.rule_records)
                        load.write_issues(conn, run_id, res.dataset, res.rejected, raw, "error")
                        load.write_issues(conn, run_id, res.dataset, res.warned, raw, "warning")
                    load.mark_files_processed(conn, run_id, [
                        {"file_name": p.name, "checksum": extract.file_checksum(p),
                         "row_count": int((raw_orders["_source_file"] == p.name).sum())} for p in pending])
                    summary.rows_extracted = sum(len(raw) for _, raw in results)
                    summary.rows_rejected = sum(len(r.rejected) for r, _ in results)
                    summary.rows_warned = sum(len(r.warned) for r, _ in results)
                    summary.rows_loaded = sum(len(r.valid) for r, _ in results)
                    log("info", f"Loaded {len(p_res.valid)} products, {len(c_res.valid)} customers, "
                                f"{n_orders} orders into PostgreSQL")
                summary.status = "success"
                log("info", f"Run #{run_id} succeeded in {sum(summary.stage_durations.values()):.2f}s")
                _finish_run(conn, summary, api_source, log)
        except Exception as exc:  # noqa: BLE001 - record any failure on the run row
            summary.status = "failed"
            summary.error = f"{exc.__class__.__name__}: {exc}"
            log("error", f"Run #{run_id} failed — {summary.error}")
            _finish_run(engine, summary, api_source, log)
            raise
        return summary


def pending_files(engine: Engine, settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    with engine.connect() as conn:
        processed = dict(conn.execute(text("SELECT file_name, checksum FROM etl.processed_files")).all())
    return [p.name for p in extract.list_pending_order_files(settings.orders_dir, processed)]
