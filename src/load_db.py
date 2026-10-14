"""
Load data/raw/*.csv into data/analytics.duckdb using sql/schema.sql.

Run:  python src/load_db.py
"""

from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "analytics.duckdb"
SCHEMA = ROOT / "sql" / "schema.sql"

TABLES = {
    "dim_customer": "dim_customer.csv",
    "dim_product": "dim_product.csv",
    "dim_date": "dim_date.csv",
    "fact_orders": "fact_orders.csv",
    "fact_order_items": "fact_order_items.csv",
}


def main() -> None:
    if DB.exists():
        DB.unlink()
    con = duckdb.connect(str(DB))
    con.execute(SCHEMA.read_text(encoding="utf-8"))

    print("Loading raw CSVs into DuckDB...")
    for table, fname in TABLES.items():
        path = (RAW / fname).as_posix()
        con.execute(
            f"INSERT INTO {table} "
            f"SELECT * FROM read_csv_auto('{path}', header=true)"
        )
        n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<18} {n:>8,} rows")

    con.close()
    print(f"Done -> {DB.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
