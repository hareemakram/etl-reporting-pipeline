import os
from pathlib import Path

import pandas as pd
import pytest

from etl.config import Settings

TEST_DB = os.getenv("TEST_DATABASE_URL")
TODAY = pd.Timestamp("2025-01-15")

CUSTOMERS_CSV = """customer_id,first_name,last_name,email,region,country,signup_date
C00001,Ava,Smith,ava@example.com,Europe,Germany,2022-01-10
C00002,  LIAM ,brown, LIAM@EXAMPLE.COM ,north america,United States,2023/03/05
C00003,Mia,Khan,mia-at-example.com,Europe,France,2022-02-01
C00004,Noah,Kim,noah@example.com,Atlantis,Nowhere,2022-02-01
C00001,Ava,Smith,ava@example.com,Europe,Germany,2022-01-10
"""

ORDERS_CSV = """order_id,order_date,customer_id,product_id,quantity,unit_price,discount,currency,status,channel
ORD-1,2024-01-05,C00001,P0001,2,92.31,0.1,eur,completed,web
ORD-2,2024/01/06,C00002,P0002,1,50,0,USD,SHIPPED,mobile
ORD-3,2024-13-01,C00001,P0001,1,92.31,0,EUR,completed,web
ORD-4,2024-01-07,,P0001,1,92.31,0,EUR,completed,web
ORD-5,2024-01-07,C00002,P9999,1,10,0,USD,completed,web
ORD-6,2024-01-08,C00002,P0002,-3,50,0,USD,completed,web
ORD-7,2024-01-08,C00002,P0002,1,50,0,XYZ,completed,web
ORD-8,2024-01-09,C00002,P0002,60,50,0,USD,completed,marketplace
ORD-1,2024-01-05,C00001,P0001,2,92.31,0.1,EUR,completed,web
ORD-9,2024-01-09,C00003,P0002,1,50,0,USD,completed,web
"""

PRODUCTS = [
    {"product_id": "P0001", "name": "Headphones", "category": "Electronics", "list_price_usd": 100.0, "active": True},
    {"product_id": "P0002", "name": "Yoga Mat", "category": "Sports", "list_price_usd": 50.0, "active": True},
]
FX = {"USD": 1.0, "EUR": 0.9231}


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    (tmp_path / "orders").mkdir()
    (tmp_path / "customers.csv").write_text(CUSTOMERS_CSV)
    (tmp_path / "orders" / "orders_2024_01.csv").write_text(ORDERS_CSV)
    return tmp_path


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    import json
    d = tmp_path / "fixtures"
    d.mkdir()
    (d / "products.json").write_text(json.dumps(PRODUCTS))
    (d / "fx_rates.json").write_text(json.dumps({"base": "USD", "rates": FX}))
    return d


@pytest.fixture
def settings(raw_dir, fixtures_dir) -> Settings:
    # Port 9 is unroutable: the API extract falls back to the fixture snapshot quickly.
    return Settings(database_url=TEST_DB or "", raw_dir=raw_dir, fixtures_dir=fixtures_dir,
                    api_base_url="http://127.0.0.1:9", api_timeout_s=0.2, api_max_retries=0)


@pytest.fixture
def engine():
    if not TEST_DB:
        pytest.skip("set TEST_DATABASE_URL to run database tests")
    from etl.db import get_engine, init_db
    eng = get_engine(TEST_DB)
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS reporting CASCADE; DROP SCHEMA IF EXISTS etl CASCADE;")
    init_db(eng)
    yield eng
