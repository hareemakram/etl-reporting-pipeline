"""Validation rule catalog for each dataset.

Context keys available to checks:
    known_customers  set[str]     customer ids valid in this run or already loaded
    known_products   set[str]     product ids from the catalog
    list_prices      dict[str, float]  product_id -> list price in USD
    fx_rates         dict[str, float]  currency -> units per USD
    today            pd.Timestamp
    price_drift_threshold float
"""
from __future__ import annotations

import pandas as pd

from .transform import VALID_CHANNELS, VALID_REGIONS, VALID_STATUSES
from .validate import Rule

EMAIL_RE = r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$"


def not_null(col: str) -> Rule:
    return Rule(f"{col}_not_null", f"{col} is required", lambda df, ctx: df[col].isna(), column=col)


def unique(col: str) -> Rule:
    return Rule(
        f"{col}_unique", f"{col} must be unique (later duplicates are rejected)",
        lambda df, ctx: df[col].notna() & df.duplicated(subset=[col], keep="first"), column=col)


# -----------------------------------------------------------------------------
CUSTOMER_RULES: list[Rule] = [
    not_null("customer_id"),
    unique("customer_id"),
    Rule("customer_id_format", "customer_id must look like C00001",
         lambda df, ctx: df["customer_id"].notna() & ~df["customer_id"].str.fullmatch(r"C\d{5}", na=False),
         column="customer_id"),
    not_null("full_name"),
    Rule("email_valid", "email must be a valid address",
         lambda df, ctx: ~df["email"].str.fullmatch(EMAIL_RE, na=False), column="email"),
    Rule("region_known", f"region must be one of {sorted(VALID_REGIONS)}",
         lambda df, ctx: ~df["region"].isin(VALID_REGIONS), column="region"),
    not_null("country"),
    Rule("signup_date_valid", "signup_date must be a real date that is not in the future",
         lambda df, ctx: df["signup_date"].isna() | (df["signup_date"] > ctx["today"]), column="signup_date"),
]

# -----------------------------------------------------------------------------
PRODUCT_RULES: list[Rule] = [
    not_null("product_id"),
    unique("product_id"),
    not_null("product_name"),
    not_null("category"),
    Rule("list_price_positive", "list_price_usd must be a positive number",
         lambda df, ctx: ~(df["list_price_usd"] > 0), column="list_price_usd"),
]


# -----------------------------------------------------------------------------
def _price_drift(df: pd.DataFrame, ctx: dict) -> pd.Series:
    list_usd = df["product_id"].map(ctx["list_prices"])
    rate = df["currency"].map(ctx["fx_rates"])
    paid_usd = df["unit_price"] / rate
    drift = (paid_usd - list_usd).abs() / list_usd
    return drift > ctx["price_drift_threshold"]


ORDER_RULES: list[Rule] = [
    not_null("order_id"),
    unique("order_id"),
    not_null("customer_id"),
    not_null("product_id"),
    Rule("order_date_valid", "order_date must parse as YYYY-MM-DD or YYYY/MM/DD",
         lambda df, ctx: df["order_date"].isna(), column="order_date"),
    Rule("order_date_not_future", "order_date cannot be in the future",
         lambda df, ctx: df["order_date"] > ctx["today"], column="order_date"),
    Rule("quantity_positive_int", "quantity must be a whole number greater than 0",
         lambda df, ctx: ~((df["quantity"] > 0) & (df["quantity"] % 1 == 0)), column="quantity"),
    Rule("unit_price_positive", "unit_price must be a number greater than 0",
         lambda df, ctx: ~(df["unit_price"] > 0), column="unit_price"),
    Rule("discount_in_range", "discount must be between 0 and 0.6",
         lambda df, ctx: ~df["discount"].between(0, 0.6), column="discount"),
    Rule("currency_supported", "currency must have an FX rate from the API",
         lambda df, ctx: ~df["currency"].isin(set(ctx["fx_rates"])), column="currency"),
    Rule("status_known", f"status must be one of {sorted(VALID_STATUSES)}",
         lambda df, ctx: ~df["status"].isin(VALID_STATUSES), column="status"),
    Rule("channel_known", f"channel must be one of {sorted(VALID_CHANNELS)}",
         lambda df, ctx: ~df["channel"].isin(VALID_CHANNELS), column="channel"),
    Rule("customer_exists", "customer_id must exist in the customer master",
         lambda df, ctx: df["customer_id"].notna() & ~df["customer_id"].isin(ctx["known_customers"]),
         column="customer_id"),
    Rule("product_exists", "product_id must exist in the product catalog",
         lambda df, ctx: df["product_id"].notna() & ~df["product_id"].isin(ctx["known_products"]),
         column="product_id"),
    # ---- warnings: loaded, but flagged for review ----
    Rule("quantity_outlier", "quantity above 50 units is unusual for retail",
         lambda df, ctx: df["quantity"] > 50, severity="warning", column="quantity"),
    Rule("price_drift", "unit price differs from catalog list price by more than the threshold",
         _price_drift, severity="warning", column="unit_price"),
]
