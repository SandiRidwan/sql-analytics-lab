"""
Run sql/transform.sql against the DuckDB file and print the marts.

Run:  python src/run_transform.py
"""

from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "analytics.duckdb"
TRANSFORM = ROOT / "sql" / "transform.sql"


def run() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(DB))
    con.execute(TRANSFORM.read_text(encoding="utf-8"))
    return con


def _show(con, title: str, sql: str, limit: int = 8) -> None:
    print(f"\n=== {title} ===")
    rel = con.execute(sql)
    cols = [d[0] for d in rel.description]
    print("  " + " | ".join(cols))
    for row in rel.fetchmany(limit):
        print("  " + " | ".join(str(v) for v in row))


def main() -> None:
    con = run()

    _show(con, "Monthly revenue (MoM + rolling)",
          "SELECT month_key, revenue, mom_pct, rolling_3m FROM mart_monthly_revenue "
          "ORDER BY month_key LIMIT 6")

    _show(con, "Top regions (latest month)",
          "SELECT month_key, region, revenue, rank_in_month FROM mart_region_rank "
          "WHERE rank_in_month <= 3 ORDER BY month_key DESC LIMIT 6")

    _show(con, "Top customers by revenue",
          "SELECT customer_id, region, order_count, total_revenue, recency_rank "
          "FROM mart_customer_orders ORDER BY recency_rank LIMIT 5")

    _show(con, "Data-quality issues",
          "SELECT check_name, severity, bad_rows FROM dq_issues ORDER BY bad_rows DESC")

    con.close()


if __name__ == "__main__":
    main()
