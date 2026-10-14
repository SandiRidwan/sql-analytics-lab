"""
PostgreSQL query-performance lab.

Runs the same query two ways against a real PostgreSQL instance and reports the
measured before/after, with EXPLAIN ANALYZE captured for the before and after.

Why PostgreSQL and not an embedded engine: on a row store, an index and a rewrite
actually change the plan, so "query performance improvement" is a real number
instead of noise.

Connection (override with env vars):
    PGHOST=localhost PGPORT=5432 PGUSER=postgres PGPASSWORD=postgres
Schema is created in the dedicated database `sql_lab`.

Run:  python src/pg_lab.py
Out:  reports/tables/pg_query_timings.csv
      reports/plans/*.txt  (EXPLAIN ANALYZE before/after)
"""

from __future__ import annotations

import csv
import os
import statistics
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT_TABLES = ROOT / "reports" / "tables"
OUT_PLANS = ROOT / "reports" / "plans"
DBNAME = "sql_lab"
RUNS = 5


def _load_done() -> bool:
    """Skip the (slow) load if the tables are already populated."""
    try:
        con = _conn()
        cur = con.cursor()
        cur.execute("SELECT count(*) FROM fact_order_items")
        n = cur.fetchone()[0]
        con.close()
        return n > 0
    except Exception:
        return False

DDL = """
DROP TABLE IF EXISTS fact_order_items CASCADE;
DROP TABLE IF EXISTS fact_orders CASCADE;
DROP TABLE IF EXISTS dim_customer CASCADE;
DROP TABLE IF EXISTS dim_product CASCADE;

CREATE TABLE dim_customer (
    customer_id integer PRIMARY KEY,
    customer_name text,
    region text,
    segment text,
    joined_at date
);
CREATE TABLE dim_product (
    product_id integer PRIMARY KEY,
    sku text, category text, list_price numeric(10,2), is_active boolean
);
CREATE TABLE fact_orders (
    order_id integer, customer_id integer, order_date date,
    channel text, status text
);
CREATE TABLE fact_order_items (
    order_item_id integer PRIMARY KEY, order_id integer, product_id integer,
    quantity integer, unit_price numeric(10,2)
);
"""


def _conn():
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "postgres"),
        dbname=DBNAME,
        connect_timeout=8,
    )


def _setup_database() -> None:
    """Create the sql_lab database if missing (connect to 'postgres' first)."""
    import psycopg2
    admin = psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "postgres"),
        dbname="postgres", connect_timeout=8,
    )
    admin.autocommit = True
    cur = admin.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DBNAME,))
    if not cur.fetchone():
        cur.execute(f'CREATE DATABASE {DBNAME}')
        print(f"  created database {DBNAME}")
    admin.close()


def _load(cur) -> None:
    cur.execute(DDL)
    jobs = [
        ("dim_customer", "customer_id,customer_name,region,segment,joined_at"),
        ("dim_product", "product_id,sku,category,list_price,is_active"),
        ("fact_orders", "order_id,customer_id,order_date,channel,status"),
        ("fact_order_items", "order_item_id,order_id,product_id,quantity,unit_price"),
    ]
    for table, cols in jobs:
        with open(RAW / f"{table}.csv", encoding="utf-8") as f:
            cur.copy_expert(
                f"COPY {table}({cols}) FROM STDIN WITH CSV HEADER", f)
        cur.execute(f"SELECT count(*) FROM {table}")
        print(f"  {table:<18} {cur.fetchone()[0]:>8,} rows")


def _median_ms(cur, sql: str, runs: int = RUNS) -> float:
    cur.execute(sql)  # warm-up
    cur.fetchall()
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        cur.execute(sql)
        cur.fetchall()
        samples.append((time.perf_counter() - t0) * 1000)
    return round(statistics.median(samples), 2)


def _plan(cur, sql: str) -> str:
    cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + sql)
    return "\n".join(r[0] for r in cur.fetchall())


def run_case(cur, name: str, slow: str, fast: str, setup_fast="") -> dict:
    before = _median_ms(cur, slow)
    plan_before = _plan(cur, slow)
    if setup_fast:
        cur.execute(setup_fast)
    after = _median_ms(cur, fast)
    plan_after = _plan(cur, fast)

    OUT_PLANS.mkdir(parents=True, exist_ok=True)
    slug = name.split(".")[0].strip().replace(" ", "_")
    (OUT_PLANS / f"{slug}_before.txt").write_text(plan_before, encoding="utf-8")
    (OUT_PLANS / f"{slug}_after.txt").write_text(plan_after, encoding="utf-8")

    return {
        "case": name,
        "before_ms": before,
        "after_ms": after,
        "speedup_x": round(before / after, 2) if after else None,
    }


def main() -> None:
    print("Setting up PostgreSQL lab database...")
    _setup_database()
    con = _conn()
    con.autocommit = True
    cur = con.cursor()
    if _load_done():
        print("  tables already loaded, skipping reload")
    else:
        _load(cur)
    cur.execute("ANALYZE")
    print("Benchmarking...\n")

    results = []

    # Case 1: SARGability — function on the column defeats the index.
    results.append(run_case(
        cur,
        "1. Function on column (SARGability)",
        slow=("SELECT count(*) FROM fact_orders o JOIN fact_order_items i "
              "ON i.order_id=o.order_id WHERE date_part('year', o.order_date)=2025"),
        fast=("SELECT count(*) FROM fact_orders o JOIN fact_order_items i "
              "ON i.order_id=o.order_id WHERE o.order_date >= DATE '2025-01-01' "
              "AND o.order_date < DATE '2026-01-01'"),
        setup_fast="CREATE INDEX IF NOT EXISTS idx_orders_date ON fact_orders(order_date)",
    ))

    # Case 2: recompute a heavy join vs read a pre-aggregated table.
    results.append(run_case(
        cur,
        "2. Recompute vs pre-aggregated table",
        slow=("SELECT c.region, sum(i.quantity*i.unit_price) rev "
              "FROM fact_order_items i JOIN fact_orders o ON o.order_id=i.order_id "
              "JOIN dim_customer c ON c.customer_id=o.customer_id "
              "GROUP BY c.region ORDER BY rev DESC"),
        fast="SELECT region, rev FROM agg_region_revenue ORDER BY rev DESC",
        setup_fast=("CREATE MATERIALIZED VIEW IF NOT EXISTS agg_region_revenue AS "
                    "SELECT c.region, sum(i.quantity*i.unit_price) rev "
                    "FROM fact_order_items i JOIN fact_orders o ON o.order_id=i.order_id "
                    "JOIN dim_customer c ON c.customer_id=o.customer_id "
                    "GROUP BY c.region"),
    ))

    # Case 3: correlated subquery per row vs a single grouped join.
    # Scoped to 500 customers so the demo is fast; the plan shape is identical
    # at full scale (the correlated form repeats the inner scan per outer row).
    results.append(run_case(
        cur,
        "3. Correlated subquery per row",
        slow=("SELECT c.customer_id, "
              "(SELECT sum(i.quantity*i.unit_price) FROM fact_order_items i "
              " JOIN fact_orders o ON o.order_id=i.order_id "
              " WHERE o.customer_id=c.customer_id) rev FROM dim_customer c "
              "WHERE c.customer_id <= 500"),
        fast=("SELECT c.customer_id, coalesce(r.rev,0) rev FROM dim_customer c "
              "LEFT JOIN (SELECT o.customer_id, sum(i.quantity*i.unit_price) rev "
              "  FROM fact_order_items i JOIN fact_orders o ON o.order_id=i.order_id "
              "  GROUP BY o.customer_id) r ON r.customer_id=c.customer_id "
              "WHERE c.customer_id <= 500"),
    ))

    con.close()

    for r in results:
        print(f"{r['case']}")
        print(f"  before {r['before_ms']:>8.2f} ms")
        print(f"  after  {r['after_ms']:>8.2f} ms   {r['speedup_x']}x")
        print()

    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    path = OUT_TABLES / "pg_query_timings.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["case", "before_ms", "after_ms", "speedup_x"])
        w.writeheader()
        w.writerows(results)
    print(f"Wrote {path.relative_to(ROOT)} and {OUT_PLANS.relative_to(ROOT)}/*.txt")


if __name__ == "__main__":
    main()
