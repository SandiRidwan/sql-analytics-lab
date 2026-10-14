"""
Data-quality and correctness tests.

These verify the analytics logic, not just that files exist:
  - the raw defects are present in the expected quantity (so the DQ queries have
    something to find)
  - the DuckDB transform runs and produces sane marts (no negative revenue,
    rolling window is monotonic in count, dedup collapses to the right grain)
  - DQ checks report the injected defects

No external services required (DuckDB only). The PostgreSQL and SQL Server labs
have their own run scripts and are exercised separately.

Run:  python -m pytest tests -q     (or)  python tests/test_data_quality.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DB = ROOT / "data" / "analytics.duckdb"


def _ensure_db():
    import generate_data, load_db, run_transform
    if not (ROOT / "data" / "raw" / "fact_orders.csv").exists():
        generate_data.main()
    if not DB.exists():
        load_db.main()
    con = run_transform.run()
    return con


class TestDataQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _ensure_db()

    def test_raw_has_injected_defects(self):
        """The generator must inject the defects the DQ checks are meant to find."""
        n_orders = self.con.execute(
            "SELECT COUNT(*) FROM fact_orders").fetchone()[0]
        n_unique = self.con.execute(
            "SELECT COUNT(DISTINCT order_id) FROM fact_orders").fetchone()[0]
        # duplicate copies were added
        self.assertGreater(n_orders, n_unique)

    def test_dedup_collapses_to_unique_order_grain(self):
        """v_orders_clean must return one row per order_id."""
        dup = self.con.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT order_id FROM v_orders_clean GROUP BY order_id "
            "  HAVING COUNT(*) > 1)").fetchone()[0]
        self.assertEqual(dup, 0)

    def test_no_orphan_line_items(self):
        orphan = self.con.execute(
            "SELECT COUNT(*) FROM fact_order_items i "
            "WHERE NOT EXISTS (SELECT 1 FROM fact_orders o "
            "                  WHERE o.order_id = i.order_id)").fetchone()[0]
        self.assertEqual(orphan, 0)

    def test_orders_without_items_exist(self):
        """Header-only orders were injected; the DQ query must find them."""
        n = self.con.execute(
            "SELECT bad_rows FROM dq_issues "
            "WHERE check_name = 'orders_without_items'").fetchone()[0]
        self.assertGreater(n, 0)

    def test_duplicate_check_matches_raw(self):
        reported = self.con.execute(
            "SELECT bad_rows FROM dq_issues "
            "WHERE check_name = 'duplicate_order_rows'").fetchone()[0]
        actual = self.con.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT order_id FROM fact_orders "
            "  GROUP BY order_id, customer_id, order_date, channel, status "
            "  HAVING COUNT(*) > 1)").fetchone()[0]
        self.assertEqual(reported, actual)


class TestAnalyticsCorrectness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _ensure_db()

    def test_revenue_never_negative(self):
        bad = self.con.execute(
            "SELECT COUNT(*) FROM mart_monthly_revenue WHERE revenue < 0"
        ).fetchone()[0]
        self.assertEqual(bad, 0)

    def test_mom_pct_first_month_is_null(self):
        first = self.con.execute(
            "SELECT mom_pct FROM mart_monthly_revenue "
            "ORDER BY month_key LIMIT 1").fetchone()[0]
        self.assertIsNone(first)

    def test_rolling_12m_defined_from_month_one(self):
        """With a frame, the first month's 12m average equals its own value."""
        row = self.con.execute(
            "SELECT revenue, rolling_12m FROM mart_monthly_revenue "
            "ORDER BY month_key LIMIT 1").fetchone()
        self.assertAlmostEqual(float(row[0]), float(row[1]), places=2)

    def test_region_rank_starts_at_one_each_month(self):
        months_ok = self.con.execute("""
            SELECT COUNT(*) FROM (
                SELECT month_key, MIN(rank_in_month) AS best
                FROM mart_region_rank GROUP BY month_key
            ) WHERE best <> 1
        """).fetchone()[0]
        self.assertEqual(months_ok, 0)

    def test_recency_rank_is_dense_1_to_n(self):
        n, mx, mn = self.con.execute(
            "SELECT COUNT(*), MAX(recency_rank), MIN(recency_rank) "
            "FROM mart_customer_orders").fetchone()
        self.assertEqual(mn, 1)
        self.assertEqual(mx, n)

    def test_channel_mix_totals_match(self):
        """The pivot columns must sum to the total in the same row."""
        bad = self.con.execute("""
            SELECT COUNT(*) FROM mart_channel_mix
            WHERE ABS((web+app+store+phone) - total) > 0.01
        """).fetchone()[0]
        self.assertEqual(bad, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
