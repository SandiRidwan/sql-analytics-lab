"""
Generate the sample warehouse used by every query in this lab.

Deterministic (fixed seed) so the numbers in the README are reproducible.

The schema is a small retail/ops star:
    dim_customer, dim_product, dim_date
    fact_orders (header) 1--* fact_order_items (lines)

It ships with three deliberate data defects, because the interesting SQL is the
SQL that finds and fixes them:

  1. Orders with no line items (header-only rows)      -> referential integrity
  2. Duplicate order copies (same order_id twice)      -> dedup at grain
  3. A late-arriving date to test gaps-and-islands     -> window functions

Run:  python src/generate_data.py
Out:  data/raw/*.csv  (then src/load_db.py loads them into data/analytics.duckdb)
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

SEED = 20261014
N_CUSTOMERS = 5_000
N_PRODUCTS = 400
N_ORDERS = 60_000
START = date(2024, 1, 1)
DAYS = 730  # two years

REGIONS = ["North", "South", "East", "West", "Central"]
CATEGORIES = ["Hardware", "Garden", "Kitchen", "Toys", "Sports", "Office"]
CHANNELS = ["web", "app", "store", "phone"]


def _write(name: str, header: list[str], rows: list[list]) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / name
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  wrote {path.relative_to(ROOT)}  ({len(rows):,} rows)")


def gen_customers(rng: random.Random) -> list[list]:
    rows = []
    for cid in range(1, N_CUSTOMERS + 1):
        # ~1.5% of customers have a missing region on purpose
        region = "" if rng.random() < 0.015 else rng.choice(REGIONS)
        rows.append([
            cid,
            f"Customer {cid:05d}",
            region,
            f"Segment {rng.randint(1, 4)}",
            (START - timedelta(days=rng.randint(0, 900))).isoformat(),
        ])
    return rows


def gen_products(rng: random.Random) -> list[list]:
    rows = []
    for pid in range(1, N_PRODUCTS + 1):
        rows.append([
            pid,
            f"SKU-{pid:04d}",
            rng.choice(CATEGORIES),
            round(rng.uniform(3.0, 250.0), 2),
            rng.choice([True, False]),
        ])
    return rows


def gen_orders_and_items(rng: random.Random):
    orders = []
    items = []
    item_id = 1
    for oid in range(1, N_ORDERS + 1):
        d = START + timedelta(days=rng.randint(0, DAYS - 1))
        cid = rng.randint(1, N_CUSTOMERS)
        channel = rng.choice(CHANNELS)
        status = rng.choices(
            ["completed", "cancelled", "returned"],
            weights=[0.86, 0.09, 0.05])[0]
        # ~2% of orders are header-only (no items) - a real defect
        n_items = 0 if rng.random() < 0.02 else rng.randint(1, 4)
        orders.append([oid, cid, d.isoformat(), channel, status])
        for _ in range(n_items):
            pid = rng.randint(1, N_PRODUCTS)
            qty = rng.randint(1, 6)
            unit = round(rng.uniform(3.0, 250.0), 2)
            items.append([item_id, oid, pid, qty, unit])
            item_id += 1

    # defect 2: duplicate the last 1.2% of orders (a double-load)
    dup_count = int(N_ORDERS * 0.012)
    for oid in range(N_ORDERS - dup_count + 1, N_ORDERS + 1):
        src = next(o for o in orders if o[0] == oid)
        orders.append([src[0], src[1], src[2], src[3], src[4]])  # same order_id

    return orders, items


def gen_calendar() -> list[list]:
    rows = []
    d = START
    while d <= START + timedelta(days=DAYS + 60):
        rows.append([
            d.isoformat(),
            d.year,
            ((d.month - 1) // 3) + 1,  # quarter
            d.month,
            d.isocalendar()[1],        # iso week
            d.strftime("%A"),
            bool(d.weekday() >= 5),    # is_weekend
        ])
        d += timedelta(days=1)
    return rows


def main() -> None:
    rng = random.Random(SEED)
    print("Generating sample warehouse (seed=%d)..." % SEED)

    _write("dim_customer.csv",
           ["customer_id", "customer_name", "region", "segment", "joined_at"],
           gen_customers(rng))
    _write("dim_product.csv",
           ["product_id", "sku", "category", "list_price", "is_active"],
           gen_products(rng))

    orders, items = gen_orders_and_items(rng)
    _write("fact_orders.csv",
           ["order_id", "customer_id", "order_date", "channel", "status"],
           orders)
    _write("fact_order_items.csv",
           ["order_item_id", "order_id", "product_id", "quantity", "unit_price"],
           items)
    _write("dim_date.csv",
           ["date_key", "year", "quarter", "month", "iso_week", "weekday",
            "is_weekend"],
           gen_calendar())

    print("Done. Next: python src/load_db.py")


if __name__ == "__main__":
    main()
