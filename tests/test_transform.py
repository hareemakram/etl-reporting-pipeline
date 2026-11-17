import pandas as pd

from etl import transform
from etl.extract import read_csv


def test_clean_customers_normalises_without_dropping(raw_dir):
    df = transform.clean_customers(read_csv(raw_dir / "customers.csv"))
    assert len(df) == 5                                     # cleaning never drops rows
    liam = df[df.customer_id == "C00002"].iloc[0]
    assert liam.full_name == "Liam Brown"
    assert liam.email == "liam@example.com"
    assert liam.region == "North America"                   # case-insensitive lookup
    assert liam.signup_date == pd.Timestamp("2023-03-05")   # slash dates accepted


def test_clean_orders_coerces_bad_values_to_nan(raw_dir):
    df = transform.clean_orders(read_csv(raw_dir / "orders" / "orders_2024_01.csv"))
    by_id = df.set_index("_source_row")
    assert pd.isna(by_id.loc[4, "order_date"])               # 2024-13-01
    assert by_id.loc[2, "currency"] == "EUR"                  # upper-cased
    assert by_id.loc[3, "status"] == "shipped"                # lower-cased
    assert df["_source_file"].eq("orders_2024_01.csv").all()


def test_enrich_converts_to_usd_after_discount():
    orders = pd.DataFrame({"quantity": [2.0], "unit_price": [92.31], "discount": [0.1], "currency": ["EUR"],
                           "order_date": [pd.Timestamp("2024-01-05")]})
    out = transform.enrich_orders(orders, pd.DataFrame(), {"EUR": 0.9231})
    assert out.loc[0, "revenue_usd"] == round(2 * 92.31 * 0.9 / 0.9231, 2)
    assert out.loc[0, "quantity"] == 2 and isinstance(out.loc[0, "order_date"], type(pd.Timestamp(0).date()))
