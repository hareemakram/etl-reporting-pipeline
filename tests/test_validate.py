import pandas as pd

from etl import transform
from etl.extract import read_csv
from etl.rules import CUSTOMER_RULES, ORDER_RULES
from etl.validate import Rule, run_rules

from .conftest import FX, TODAY


def test_framework_separates_errors_and_warnings():
    df = pd.DataFrame({"x": [1, -1, 100, None]})
    rules = [
        Rule("x_present", "required", lambda d, c: d["x"].isna()),
        Rule("x_positive", "positive", lambda d, c: d["x"] < 0),
        Rule("x_large", "large", lambda d, c: d["x"] > 50, severity="warning"),
    ]
    res = run_rules(df, rules, "t")
    assert list(res.rejected.index) == [1, 3]
    assert res.rejected.loc[1, "_reasons"] == ["x_positive"]
    assert list(res.warned.index) == [2]
    assert list(res.valid.index) == [0, 2]
    assert res.valid["_flagged"].tolist() == [False, True]
    assert {r["rule_name"]: r["rows_failed"] for r in res.rule_records} == {"x_present": 1, "x_positive": 1, "x_large": 1}


def test_rejected_row_lists_every_failed_rule():
    df = pd.DataFrame({"a": [None], "b": [None]})
    rules = [Rule("a_req", "", lambda d, c: d["a"].isna()), Rule("b_req", "", lambda d, c: d["b"].isna())]
    assert run_rules(df, rules, "t").rejected.iloc[0]["_reasons"] == ["a_req", "b_req"]


def test_customer_rules(raw_dir):
    df = transform.clean_customers(read_csv(raw_dir / "customers.csv"))
    res = run_rules(df, CUSTOMER_RULES, "customers", {"today": TODAY})
    reasons = dict(zip(res.rejected["customer_id"] + "@" + res.rejected["_source_row"].astype(str), res.rejected["_reasons"]))
    assert reasons == {"C00003@4": ["email_valid"], "C00004@5": ["region_known"], "C00001@6": ["customer_id_unique"]}
    assert sorted(res.valid["customer_id"]) == ["C00001", "C00002"]


def test_order_rules(raw_dir):
    df = transform.clean_orders(read_csv(raw_dir / "orders" / "orders_2024_01.csv"))
    ctx = {"today": TODAY, "known_customers": {"C00001", "C00002"}, "known_products": {"P0001", "P0002"},
           "list_prices": {"P0001": 100.0, "P0002": 50.0}, "fx_rates": FX, "price_drift_threshold": 0.35}
    res = run_rules(df, ORDER_RULES, "orders", ctx)
    rejected = dict(zip(res.rejected["_source_row"], res.rejected["_reasons"]))
    assert rejected == {
        4: ["order_date_valid"],
        5: ["customer_id_not_null"],
        6: ["product_exists"],
        7: ["quantity_positive_int"],
        8: ["currency_supported"],
        10: ["order_id_unique"],
        11: ["customer_exists"],
    }
    assert res.warned["order_id"].tolist() == ["ORD-8"]
    assert res.warned.iloc[0]["_reasons"] == ["quantity_outlier"]
    assert sorted(res.valid["order_id"]) == ["ORD-1", "ORD-2", "ORD-8"]
