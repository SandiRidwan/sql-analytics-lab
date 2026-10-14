"""
Microsoft SQL Server (T-SQL) lab.

Loads the same sample warehouse into a real SQL Server instance and runs the
T-SQL queries that a data-analyst job actually asks about: CTEs, window
functions (ROW_NUMBER, RANK, LAG), gaps-and-islands, and de-duplication at grain.

Connection (override with env vars):
    SQLSERVER=localhost  (or localhost\\SQLEXPRESS, Trusted_Connection=yes)
Uses ODBC Driver 17. Database: SqlLab.

Run:  python src/tsql_lab.py
Out:  prints one result table per query
      reports/tables/tsql_results.md  (captured results for the README)
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "reports" / "tables"
DB = "SqlLab"
SERVER = os.environ.get("SQLSERVER", "localhost")

DDL = f"""
IF DB_ID('{DB}') IS NULL CREATE DATABASE [{DB}];
"""
USE = f"USE [{DB}];"

TABLES = """
IF OBJECT_ID('fact_order_items','U') IS NOT NULL DROP TABLE fact_order_items;
IF OBJECT_ID('fact_orders','U') IS NOT NULL DROP TABLE fact_orders;
IF OBJECT_ID('dim_customer','U') IS NOT NULL DROP TABLE dim_customer;
IF OBJECT_ID('dim_product','U') IS NOT NULL DROP TABLE dim_product;

CREATE TABLE dim_customer (
    customer_id int PRIMARY KEY, customer_name nvarchar(100),
    region nvarchar(40), segment nvarchar(40), joined_at date);
CREATE TABLE dim_product (
    product_id int PRIMARY KEY, sku nvarchar(40), category nvarchar(40),
    list_price decimal(10,2), is_active bit);
CREATE TABLE fact_orders (
    order_id int, customer_id int, order_date date,
    channel nvarchar(20), status nvarchar(20));
CREATE TABLE fact_order_items (
    order_item_id int PRIMARY KEY, order_id int, product_id int,
    quantity int, unit_price decimal(10,2));
"""

# The T-SQL queries. Each is (title, sql). Every one exercises a technique the
# job spec names: CTE, window function, dedup, gaps-and-islands, aggregation.
QUERIES: list[tuple[str, str]] = [
    ("Q1  Month-over-month revenue (CTE + LAG)", """
WITH monthly AS (
    SELECT DATEFROMPARTS(YEAR(o.order_date), MONTH(o.order_date), 1) AS month_key,
           SUM(i.quantity * i.unit_price) AS revenue
    FROM fact_orders o JOIN fact_order_items i ON i.order_id = o.order_id
    WHERE o.status = 'completed'
    GROUP BY DATEFROMPARTS(YEAR(o.order_date), MONTH(o.order_date), 1)
)
SELECT month_key, revenue,
       LAG(revenue) OVER (ORDER BY month_key) AS prev_revenue,
       ROUND((revenue - LAG(revenue) OVER (ORDER BY month_key))
             / NULLIF(LAG(revenue) OVER (ORDER BY month_key),0) * 100, 2) AS mom_pct
FROM monthly ORDER BY month_key;
"""),

    ("Q2  12-month rolling average (window frame)", """
WITH monthly AS (
    SELECT DATEFROMPARTS(YEAR(order_date), MONTH(order_date), 1) AS month_key,
           SUM(quantity * unit_price) AS revenue
    FROM fact_orders o JOIN fact_order_items i ON i.order_id = o.order_id
    WHERE status = 'completed'
    GROUP BY DATEFROMPARTS(YEAR(order_date), MONTH(order_date), 1)
)
SELECT month_key, revenue,
       ROUND(AVG(revenue) OVER (ORDER BY month_key
             ROWS BETWEEN 11 PRECEDING AND CURRENT ROW), 2) AS rolling_12m
FROM monthly ORDER BY month_key;
"""),

    ("Q3  Top-3 regions per month (ROW_NUMBER)", """
WITH region_month AS (
    SELECT DATEFROMPARTS(YEAR(o.order_date), MONTH(o.order_date), 1) AS month_key,
           c.region, SUM(i.quantity * i.unit_price) AS revenue
    FROM fact_orders o
    JOIN fact_order_items i ON i.order_id = o.order_id
    JOIN dim_customer c ON c.customer_id = o.customer_id
    WHERE o.status = 'completed' AND c.region IS NOT NULL AND c.region <> ''
    GROUP BY DATEFROMPARTS(YEAR(o.order_date), MONTH(o.order_date), 1), c.region
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY month_key ORDER BY revenue DESC) AS rn
    FROM region_month
)
SELECT month_key, region, revenue, rn FROM ranked WHERE rn <= 3
ORDER BY month_key DESC, rn;
"""),

    ("Q4  De-duplicate orders at grain (ROW_NUMBER dedup)", """
WITH numbered AS (
    SELECT order_id, customer_id, order_date, channel, status,
           ROW_NUMBER() OVER (
               PARTITION BY order_id, customer_id, order_date, channel, status
               ORDER BY order_id) AS rn
    FROM fact_orders
)
SELECT COUNT(*) AS raw_rows,
       SUM(CASE WHEN rn = 1 THEN 1 ELSE 0 END) AS deduped_rows,
       SUM(CASE WHEN rn > 1 THEN 1 ELSE 0 END) AS duplicates_removed
FROM numbered;
"""),

    ("Q5  Customer order gaps (gaps and islands)", """
WITH per_order AS (
    SELECT DISTINCT o.customer_id, o.order_id, o.order_date,
           LAG(o.order_date) OVER (
               PARTITION BY o.customer_id ORDER BY o.order_date) AS prev_date
    FROM fact_orders o JOIN fact_order_items i ON i.order_id = o.order_id
)
SELECT TOP (5) customer_id, order_date, prev_date,
       DATEDIFF(day, prev_date, order_date) AS gap_days
FROM per_order
WHERE prev_date IS NOT NULL
ORDER BY gap_days DESC;
"""),

    ("Q6  Channel mix (conditional aggregation)", """
SELECT DATEFROMPARTS(YEAR(o.order_date), MONTH(o.order_date), 1) AS month_key,
       SUM(CASE WHEN o.channel='web'   THEN i.quantity*i.unit_price ELSE 0 END) AS web,
       SUM(CASE WHEN o.channel='app'   THEN i.quantity*i.unit_price ELSE 0 END) AS app,
       SUM(CASE WHEN o.channel='store' THEN i.quantity*i.unit_price ELSE 0 END) AS store,
       SUM(CASE WHEN o.channel='phone' THEN i.quantity*i.unit_price ELSE 0 END) AS phone
FROM fact_orders o JOIN fact_order_items i ON i.order_id = o.order_id
WHERE o.status = 'completed'
GROUP BY DATEFROMPARTS(YEAR(o.order_date), MONTH(o.order_date), 1)
ORDER BY month_key;
"""),

    ("Q7  Orders with no items (anti-join data validation)", """
SELECT COUNT(*) AS orders_without_items
FROM fact_orders o
WHERE NOT EXISTS (SELECT 1 FROM fact_order_items i WHERE i.order_id = o.order_id);
"""),

    ("Q8  Running total per customer (cumulative SUM window)", """
WITH per_customer AS (
    SELECT o.customer_id, o.order_id,
           SUM(i.quantity*i.unit_price) AS order_value,
           o.order_date
    FROM fact_orders o JOIN fact_order_items i ON i.order_id = o.order_id
    WHERE o.status = 'completed'
    GROUP BY o.customer_id, o.order_id, o.order_date
)
SELECT TOP (8) customer_id, order_date, order_value,
       ROUND(SUM(order_value) OVER (
           PARTITION BY customer_id ORDER BY order_date
           ROWS UNBOUNDED PRECEDING), 2) AS running_total
FROM per_customer ORDER BY customer_id, order_date;
"""),
]


def _connect(db: str = "master"):
    import pyodbc
    for drv in ("ODBC Driver 17 for SQL Server", "SQL Server Native Client 11.0",
                "SQL Server"):
        try:
            return pyodbc.connect(
                f"DRIVER={{{drv}}};SERVER={SERVER};DATABASE={db};"
                f"Trusted_Connection=yes;", autocommit=True, timeout=10)
        except Exception:
            continue
    raise RuntimeError("No SQL Server ODBC driver / connection available")


def _bulk_insert(cur, table: str, csv_name: str, cols: str) -> int:
    """Insert a CSV via parameterised batches (no BULK INSERT permissions)."""
    import csv as _csv
    path = RAW / csv_name
    with open(path, encoding="utf-8") as f:
        rows = list(_csv.reader(f))
    header = rows[0]
    data = rows[1:]

    # normalise values SQL Server will not accept as-is via ODBC parameters
    def norm(v: str):
        if v == "":
            return None
        if v in ("True", "true"):
            return 1
        if v in ("False", "false"):
            return 0
        return v

    data = [tuple(norm(v) for v in row) for row in data]

    placeholders = ",".join("?" for _ in header)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
    cur.fast_executemany = True
    # batch to avoid the 2100-parameter limit (cols=5 -> batch of 400)
    B = 400
    for i in range(0, len(data), B):
        cur.executemany(sql, data[i:i+B])
    return len(data)


def main() -> None:
    if not (RAW / "fact_orders.csv").exists():
        raise SystemExit("Run `python src/generate_data.py` first.")

    print(f"Connecting to SQL Server ({SERVER})...")
    con = _connect("master")
    con.cursor().execute(DDL)
    con.close()

    con = _connect(DB)
    cur = con.cursor()
    cur.execute(USE)
    print("  creating tables...")
    for stmt in TABLES.strip().split(";\n\n"):
        if stmt.strip():
            cur.execute(stmt)

    print("  loading rows...")
    _bulk_insert(cur, "dim_customer", "dim_customer.csv",
                 "customer_id,customer_name,region,segment,joined_at")
    _bulk_insert(cur, "dim_product", "dim_product.csv",
                 "product_id,sku,category,list_price,is_active")
    _bulk_insert(cur, "fact_orders", "fact_orders.csv",
                 "order_id,customer_id,order_date,channel,status")
    _bulk_insert(cur, "fact_order_items", "fact_order_items.csv",
                 "order_item_id,order_id,product_id,quantity,unit_price")
    print("  loaded.")

    OUT.mkdir(parents=True, exist_ok=True)
    md = ["# T-SQL query results (SQL Server)\n"]
    for title, sql in QUERIES:
        print(f"\n=== {title} ===")
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(6)
        print("  " + " | ".join(cols))
        for r in rows:
            print("  " + " | ".join(str(v) for v in r))
        md.append(f"\n## {title}\n")
        md.append("| " + " | ".join(cols) + " |")
        md.append("|" + "|".join("---" for _ in cols) + "|")
        for r in rows:
            md.append("| " + " | ".join(str(v) for v in r) + " |")

    con.close()
    (OUT / "tsql_results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nWrote {(OUT / 'tsql_results.md').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
