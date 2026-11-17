"""A stand-in for an upstream REST API (product catalog + FX rates).

It behaves like a real third-party API would: paginated responses and
occasional transient 503s (``MOCK_API_FAILURE_RATE``), which exercises the
extractor's retry/backoff logic. Point ``API_BASE_URL`` at any compatible
service to swap it out.
"""
from __future__ import annotations

import json
import os
import random
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query

from etl.config import get_settings

router = APIRouter(prefix="/mock-api", tags=["mock upstream API"])


def _failure_rate() -> float:
    try:
        return float(os.getenv("MOCK_API_FAILURE_RATE", "0.15"))
    except ValueError:
        return 0.0


def _maybe_fail() -> None:
    if random.random() < _failure_rate():
        raise HTTPException(status_code=503, detail="upstream temporarily unavailable")


@lru_cache(maxsize=1)
def _fixture(name: str) -> dict | list:
    return json.loads((get_settings().fixtures_dir / name).read_text())


@router.get("/products")
def products(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100)):
    _maybe_fail()
    items = _fixture("products.json")
    start = (page - 1) * page_size
    chunk = items[start:start + page_size]
    has_more = start + page_size < len(items)
    return {"data": chunk, "page": page, "page_size": page_size, "total": len(items),
            "next_page": page + 1 if has_more else None}


@router.get("/fx-rates")
def fx_rates(base: str = "USD"):
    _maybe_fail()
    if base.upper() != "USD":
        raise HTTPException(status_code=400, detail="only base=USD is supported")
    body = dict(_fixture("fx_rates.json"))
    body["fetched_at"] = datetime.now(UTC).isoformat()
    return body
