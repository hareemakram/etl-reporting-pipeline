"""Command line entry point.

    python -m etl init-db                     create schemas, tables and views
    python -m etl run [--full-refresh] [--max-files N]
    python -m etl demo                        load the sample year one month per run
    python -m etl status                      show recent runs and pending files
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import text

from .config import get_settings
from .db import get_engine, init_db
from .pipeline import PipelineBusyError, pending_files, run_pipeline


def _print_summary(s) -> None:
    dur = sum(s.stage_durations.values())
    print(f"run #{s.run_id}: {s.status.upper()}  files={len(s.files)}  extracted={s.rows_extracted}  "
          f"loaded={s.rows_loaded}  rejected={s.rows_rejected}  flagged={s.rows_warned}  ({dur:.2f}s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m etl", description="ETL pipeline for reporting data")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="apply sql/schema.sql and sql/views.sql")
    run = sub.add_parser("run", help="run the pipeline once")
    run.add_argument("--full-refresh", action="store_true", help="reprocess every order file")
    run.add_argument("--max-files", type=int, default=None, help="only load the next N pending files")
    demo = sub.add_parser("demo", help="load pending files one per run to build run history")
    demo.add_argument("--leave", type=int, default=2, help="files to leave pending for a live demo")
    sub.add_parser("status", help="show recent runs and pending files")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)-7s %(message)s")
    settings = get_settings()
    engine = get_engine(settings.database_url)
    init_db(engine)

    try:
        if args.cmd == "init-db":
            print("schema ready")
        elif args.cmd == "run":
            _print_summary(run_pipeline(engine, settings, full_refresh=args.full_refresh,
                                        max_files=args.max_files))
        elif args.cmd == "demo":
            todo = max(len(pending_files(engine, settings)) - args.leave, 0)
            for _ in range(todo):
                _print_summary(run_pipeline(engine, settings, triggered_by="demo", max_files=1))
            print(f"{args.leave} file(s) left pending — trigger them from the dashboard.")
        elif args.cmd == "status":
            with engine.connect() as conn:
                for r in conn.execute(text(
                        "SELECT run_id, started_at, status, rows_loaded, rows_rejected FROM etl.pipeline_runs "
                        "ORDER BY run_id DESC LIMIT 10")):
                    print(f"#{r.run_id:<4} {r.started_at:%Y-%m-%d %H:%M}  {r.status:<8} "
                          f"loaded={r.rows_loaded:<6} rejected={r.rows_rejected}")
            print("pending:", ", ".join(pending_files(engine, settings)) or "none")
    except PipelineBusyError as exc:
        print(exc, file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"pipeline failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
