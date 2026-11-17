"""Transform: standardise raw strings into typed columns, then enrich valid rows.

``clean_*`` functions never drop rows. They trim, normalise case and coerce
types (bad values become NaN/NaT) so validation rules can judge every row.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VALID_STATUSES = {"completed", "shipped", "cancelled", "returned"}
VALID_CHANNELS = {"web", "mobile", "marketplace"}
VALID_REGIONS = {"North America", "Europe", "Asia Pacific", "Latin America"}
_REGION_LOOKUP = {r.lower(): r for r in VALID_REGIONS}


def _strip(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().replace({"": np.nan, "nan": np.nan, "None": np.nan})


def parse_dates(s: pd.Series) -> pd.Series:
    """Accept ISO (2024-05-01) and slash (2024/05/01) dates; anything else -> NaT."""
    s = _strip(s).str.replace("/", "-", regex=False)
    return pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")


def clean_customers(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["customer_id"] = _strip(df["customer_id"]).str.upper()
    first = _strip(df["first_name"]).str.title()
    last = _strip(df["last_name"]).str.title()
    df["full_name"] = (first.fillna("") + " " + last.fillna("")).str.strip().replace({"": np.nan})
    df["email"] = _strip(df["email"]).str.lower()
    region = _strip(df["region"])
    df["region"] = region.str.lower().map(_REGION_LOOKUP).fillna(region)
    df["country"] = _strip(df["country"])
    df["signup_date"] = parse_dates(df["signup_date"])
    return df


def clean_products(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    if "_source_row" not in df:
        df.insert(0, "_source_row", range(1, len(df) + 1))
        df.insert(1, "_source_file", "api:/products")
    df["product_id"] = _strip(df["product_id"]).str.upper()
    df["product_name"] = _strip(df["name"])
    df["category"] = _strip(df["category"])
    df["list_price_usd"] = pd.to_numeric(_strip(df["list_price_usd"]), errors="coerce")
    return df


def clean_orders(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["order_id"] = _strip(df["order_id"]).str.upper()
    df["customer_id"] = _strip(df["customer_id"]).str.upper()
    df["product_id"] = _strip(df["product_id"]).str.upper()
    df["order_date_raw"] = df["order_date"]
    df["order_date"] = parse_dates(df["order_date"])
    df["quantity"] = pd.to_numeric(_strip(df["quantity"]), errors="coerce")
    df["unit_price"] = pd.to_numeric(_strip(df["unit_price"]), errors="coerce")
    df["discount"] = pd.to_numeric(_strip(df["discount"]), errors="coerce").fillna(0.0)
    df["currency"] = _strip(df["currency"]).str.upper()
    df["status"] = _strip(df["status"]).str.lower()
    df["channel"] = _strip(df["channel"]).str.lower()
    return df


def enrich_orders(orders: pd.DataFrame, products: pd.DataFrame, fx_rates: dict[str, float]) -> pd.DataFrame:
    """Add USD conversion and net revenue to already-validated orders."""
    df = orders.copy()
    df["fx_rate"] = df["currency"].map(fx_rates).astype(float)
    df["quantity"] = df["quantity"].astype(int)
    gross_local = df["quantity"] * df["unit_price"]
    df["revenue_usd"] = (gross_local * (1 - df["discount"]) / df["fx_rate"]).round(2)
    df["order_date"] = df["order_date"].dt.date
    return df
