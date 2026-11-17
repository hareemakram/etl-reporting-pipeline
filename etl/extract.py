"""Extract: read raw CSV exports and pull reference data from a REST API.

All CSV columns are read as strings. Typing happens later in ``transform.clean_*``
so a bad value never crashes the reader: it becomes a validation failure instead.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pandas as pd

from .config import Settings

Log = Callable[[str, str], None]


def _noop_log(level: str, msg: str) -> None:  # pragma: no cover - default sink
    pass


def file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def read_csv(path: Path) -> pd.DataFrame:
    """Read a CSV as all-string columns and keep the 1-based source line number."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[], encoding="utf-8")
    df.insert(0, "_source_row", range(2, len(df) + 2))   # +1 header, +1 one-based
    df.insert(1, "_source_file", path.name)
    return df


def list_pending_order_files(orders_dir: Path, processed: dict[str, str]) -> list[Path]:
    """Order files not yet loaded, or whose content changed since they were loaded."""
    pending = []
    for path in sorted(orders_dir.glob("*.csv")):
        if processed.get(path.name) != file_checksum(path):
            pending.append(path)
    return pending


def read_order_files(paths: list[Path]) -> pd.DataFrame:
    if not paths:
        return pd.DataFrame(columns=["_source_row", "_source_file"])
    return pd.concat([read_csv(p) for p in paths], ignore_index=True)


# -----------------------------------------------------------------------------
# API extraction
# -----------------------------------------------------------------------------
@dataclass
class ApiResult:
    products: pd.DataFrame
    fx_rates: dict[str, float]
    source: str          # "api" or "fixture"
    requests: int
    retries: int


class ApiClient:
    """Small resilient client: retries with exponential backoff, follows pagination."""

    def __init__(self, settings: Settings, log: Log = _noop_log, client: httpx.Client | None = None):
        self.settings = settings
        self.log = log
        self.client = client or httpx.Client(base_url=settings.api_base_url, timeout=settings.api_timeout_s)
        self.requests = 0
        self.retries = 0

    def get_json(self, path: str, params: dict | None = None) -> dict:
        attempts = self.settings.api_max_retries + 1
        for attempt in range(1, attempts + 1):
            self.requests += 1
            try:
                resp = self.client.get(path, params=params)
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise httpx.HTTPStatusError(f"{resp.status_code}", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt == attempts:
                    raise
                self.retries += 1
                wait = 0.25 * 2 ** (attempt - 1)
                self.log("warning", f"GET {path} failed ({exc.__class__.__name__}: {exc}); "
                                    f"retry {attempt}/{attempts - 1} in {wait:.2f}s")
                time.sleep(wait)
        raise RuntimeError("unreachable")  # pragma: no cover

    def fetch_products(self, page_size: int = 10) -> list[dict]:
        items, page = [], 1
        while page:
            body = self.get_json("/products", params={"page": page, "page_size": page_size})
            items.extend(body["data"])
            page = body.get("next_page")
        return items

    def fetch_fx_rates(self) -> dict[str, float]:
        body = self.get_json("/fx-rates", params={"base": "USD"})
        return {k.upper(): float(v) for k, v in body["rates"].items()}


def extract_api(settings: Settings, log: Log = _noop_log, client: httpx.Client | None = None) -> ApiResult:
    """Pull the product catalog and FX rates. Falls back to the last known fixture
    snapshot if the API stays unreachable, so a flaky upstream never blocks a load."""
    api = ApiClient(settings, log, client)
    try:
        products = api.fetch_products()
        fx = api.fetch_fx_rates()
        log("info", f"API: fetched {len(products)} products and {len(fx)} FX rates "
                    f"in {api.requests} requests ({api.retries} retries)")
        return ApiResult(pd.DataFrame(products).astype(str), fx, "api", api.requests, api.retries)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log("warning", f"API unreachable after retries ({exc}); using fixture snapshot")
        products = json.loads((settings.fixtures_dir / "products.json").read_text())
        fx = json.loads((settings.fixtures_dir / "fx_rates.json").read_text())["rates"]
        return ApiResult(pd.DataFrame(products).astype(str), {k: float(v) for k, v in fx.items()},
                         "fixture", api.requests, api.retries)
