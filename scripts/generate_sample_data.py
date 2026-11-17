"""Generate realistic (and deliberately messy) sample data for the pipeline.

Outputs
-------
data/raw/customers.csv                 customer master export (CRM)
data/raw/orders/orders_2024_MM.csv     one order export per month (POS / web shop)
data/fixtures/products.json            product catalog served by the mock API
data/fixtures/fx_rates.json            currency rates served by the mock API

About 3-7% of rows carry a defect that one of the validation rules should catch:
missing keys, negative quantities, unparseable or future dates, duplicate ids,
unknown products/customers, invalid currencies, malformed emails and so on.
The defect rate drifts month to month so the data-quality trend has a story.

Usage:  python scripts/generate_sample_data.py [--seed 42]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
FIXTURES = ROOT / "data" / "fixtures"

CATALOG = {
    "Electronics": [
        ("Noise-Cancelling Headphones", 249), ("Wireless Earbuds", 129), ("4K Streaming Stick", 49),
        ("Smart Speaker", 99), ("Mechanical Keyboard", 139), ("USB-C Hub", 59), ("Portable SSD 1TB", 119),
        ("Fitness Tracker", 89),
    ],
    "Home & Kitchen": [
        ("Pour-Over Coffee Kit", 64), ("Cast Iron Skillet", 45), ("Air Purifier", 189), ("Chef's Knife", 79),
        ("Linen Bedding Set", 159), ("Robot Vacuum", 299), ("Ceramic Dinnerware Set", 119),
    ],
    "Sports & Outdoors": [
        ("Yoga Mat Pro", 68), ("Trail Running Shoes", 135), ("Insulated Water Bottle", 35),
        ("Camping Hammock", 59), ("Adjustable Dumbbells", 249), ("Cycling Helmet", 89),
    ],
    "Beauty": [
        ("Vitamin C Serum", 38), ("Hair Dryer Ionic", 129), ("Skincare Starter Set", 72),
        ("Electric Toothbrush", 89), ("Fragrance 50ml", 95),
    ],
    "Books & Media": [
        ("Data Engineering Handbook", 54), ("Bestseller Novel", 18), ("Cookbook Collection", 32),
        ("Vinyl Record", 29), ("Graphic Novel Box Set", 64),
    ],
    "Toys & Games": [
        ("Strategy Board Game", 49), ("Building Blocks Set", 89), ("Puzzle 1000pc", 24),
        ("RC Drone Mini", 79), ("Plush Bear", 22),
    ],
}

REGIONS = {
    "North America": [("United States", "USD", 0.78), ("Canada", "CAD", 0.22)],
    "Europe": [("Germany", "EUR", 0.30), ("France", "EUR", 0.22), ("United Kingdom", "GBP", 0.33), ("Netherlands", "EUR", 0.15)],
    "Asia Pacific": [("Australia", "AUD", 0.45), ("Japan", "JPY", 0.35), ("Singapore", "SGD", 0.20)],
    "Latin America": [("Brazil", "BRL", 0.55), ("Mexico", "MXN", 0.45)],
}
REGION_WEIGHTS = {"North America": 0.46, "Europe": 0.30, "Asia Pacific": 0.16, "Latin America": 0.08}

FX = {"USD": 1.0, "EUR": 0.9231, "GBP": 0.7872, "CAD": 1.3614, "AUD": 1.5236, "JPY": 151.42,
      "SGD": 1.3468, "BRL": 4.9712, "MXN": 17.0841}

FIRST = ["Ava", "Liam", "Noah", "Emma", "Mia", "Lucas", "Sofia", "Ethan", "Amir", "Zara", "Hana", "Kenji",
         "Mateo", "Valentina", "Omar", "Leila", "Chloe", "Felix", "Ines", "Ravi", "Priya", "Yuki", "Elena",
         "Diego", "Nora", "Hugo", "Aisha", "Samuel", "Clara", "Daniel"]
LAST = ["Smith", "Garcia", "Müller", "Martin", "Rossi", "Tanaka", "Khan", "Silva", "Brown", "Dubois",
        "Nguyen", "Kim", "Lopez", "Schmidt", "Wilson", "Ahmed", "Costa", "Novak", "Hernandez", "Patel"]

# Monthly demand multiplier: steady growth + holiday peak.
SEASONALITY = [0.82, 0.78, 0.90, 0.92, 0.97, 0.95, 0.98, 1.02, 1.00, 1.08, 1.38, 1.62]
# Share of rows that get a defect, per month (drifts so the DQ chart tells a story:
# a messy upstream release in May/June, then a fix, then holiday load pressure).
DEFECT_RATE = [0.040, 0.035, 0.032, 0.030, 0.062, 0.071, 0.034, 0.028, 0.025, 0.024, 0.036, 0.041]


def build_products(rng: random.Random) -> list[dict]:
    products, n = [], 1
    for category, items in CATALOG.items():
        for name, price in items:
            products.append({
                "product_id": f"P{n:04d}",
                "name": name,
                "category": category,
                "list_price_usd": round(price * rng.uniform(0.97, 1.03), 2),
                "active": True,
            })
            n += 1
    return products


def build_customers(rng: random.Random, n: int = 900) -> list[dict]:
    rows = []
    regions = list(REGION_WEIGHTS)
    for i in range(1, n + 1):
        region = rng.choices(regions, weights=[REGION_WEIGHTS[r] for r in regions])[0]
        countries = REGIONS[region]
        country = rng.choices([c[0] for c in countries], weights=[c[2] for c in countries])[0]
        first, last = rng.choice(FIRST), rng.choice(LAST)
        email = f"{first}.{last}{i}@example.com".lower().replace("ü", "u")
        signup = date(2021, 1, 1) + timedelta(days=rng.randint(0, 1250))
        row = {
            "customer_id": f"C{i:05d}", "first_name": first, "last_name": last, "email": email,
            "region": region, "country": country, "signup_date": signup.isoformat(),
        }
        # --- messiness that the "clean" step should fix (not reject) ---
        r = rng.random()
        if r < 0.04:
            row["first_name"] = f"  {first.upper()} "
        elif r < 0.07:
            row["email"] = f"  {email.upper()}"
        elif r < 0.09:
            row["region"] = region.lower()
        # --- defects that validation should reject ---
        r = rng.random()
        if r < 0.012:
            row["email"] = email.replace("@", "")            # malformed email
        elif r < 0.018:
            row["region"] = "Atlantis"                         # unknown region
        elif r < 0.022:
            row["signup_date"] = "2031-02-30"                  # impossible date
        rows.append(row)
    # A couple of exact duplicates from a bad CRM export.
    rows.extend(dict(rows[k]) for k in (17, 333, 640))
    rng.shuffle(rows)
    return rows


def build_orders(rng, month: int, products, customers, start_id: int) -> list[dict]:
    valid_customers = [c for c in customers if c["region"] in REGIONS]
    base = 620
    n = int(base * SEASONALITY[month - 1] * (1 + month * 0.012) * rng.uniform(0.96, 1.04))
    days_in_month = (date(2024 + month // 12, month % 12 + 1, 1) - date(2024, month, 1)).days
    channels = ["web", "mobile", "marketplace"]
    channel_w = [0.52, 0.31 + month * 0.006, 0.17]
    category_bias = {"Electronics": 1.4, "Home & Kitchen": 1.1, "Sports & Outdoors": 0.9,
                     "Beauty": 0.8, "Books & Media": 0.7, "Toys & Games": 0.6 + (0.9 if month >= 11 else 0)}
    pw = [category_bias[p["category"]] for p in products]
    rows = []
    for k in range(n):
        cust = rng.choice(valid_customers)
        country = cust["country"]
        currency = next(c[1] for c in REGIONS[cust["region"]] if c[0] == country)
        prod = rng.choices(products, weights=pw)[0]
        qty = rng.choices([1, 2, 3, 4, 5], weights=[62, 22, 9, 4, 3])[0]
        local_price = prod["list_price_usd"] * FX[currency]
        discount = rng.choices([0, 0.05, 0.10, 0.15, 0.20], weights=[60, 12, 14, 8, 6])[0]
        if month == 11 and rng.random() < 0.35:   # Black Friday promo
            discount = 0.25
        status = rng.choices(["completed", "shipped", "cancelled", "returned"], weights=[78, 12, 6, 4])[0]
        d = date(2024, month, rng.randint(1, days_in_month))
        rows.append({
            "order_id": f"ORD-{start_id + k:07d}",
            "order_date": d.isoformat() if rng.random() > 0.15 else d.strftime("%Y/%m/%d"),
            "customer_id": cust["customer_id"],
            "product_id": prod["product_id"],
            "quantity": qty,
            "unit_price": round(local_price, 0 if currency == "JPY" else 2),
            "discount": discount,
            "currency": currency if rng.random() > 0.05 else currency.lower(),
            "status": status if rng.random() > 0.04 else status.upper(),
            "channel": rng.choices(channels, weights=channel_w)[0],
        })

    defects = [
        ("customer_id", lambda r: ""),
        ("product_id", lambda r: "P9999"),
        ("customer_id", lambda r: "C99999"),
        ("quantity", lambda r: -abs(int(r["quantity"]))),
        ("quantity", lambda r: 0),
        ("unit_price", lambda r: 0),
        ("unit_price", lambda r: "N/A"),
        ("order_date", lambda r: "2024-13-41"),
        ("order_date", lambda r: ""),
        ("order_date", lambda r: "2027-01-15"),
        ("currency", lambda r: "XYZ"),
        ("discount", lambda r: 0.9),
        ("status", lambda r: "lost_in_space"),
        ("quantity", lambda r: rng.randint(51, 72)),         # warning only: bulk outlier
        ("unit_price", lambda r: round(float(r["unit_price"]) * 1.6, 2)),  # warning: price drift
    ]
    for r in rows:
        if rng.random() < DEFECT_RATE[month - 1]:
            col, fn = rng.choice(defects)
            r[col] = fn(r)
    # duplicated order ids (re-sent by the source system)
    for _ in range(max(2, int(n * DEFECT_RATE[month - 1] * 0.15))):
        rows.append(dict(rng.choice(rows)))
    rng.shuffle(rows)
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    products = build_products(rng)
    customers = build_customers(rng)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "products.json").write_text(json.dumps(products, indent=2))
    (FIXTURES / "fx_rates.json").write_text(json.dumps(
        {"base": "USD", "as_of": "2024-12-31", "rates": FX}, indent=2))
    write_csv(RAW / "customers.csv", customers)

    next_id = 100001
    total = 0
    for month in range(1, 13):
        rows = build_orders(rng, month, products, customers, next_id)
        next_id += len(rows) + 50
        write_csv(RAW / "orders" / f"orders_2024_{month:02d}.csv", rows)
        total += len(rows)
    print(f"products={len(products)} customers={len(customers)} orders={total} (12 monthly files)")


if __name__ == "__main__":
    main()
