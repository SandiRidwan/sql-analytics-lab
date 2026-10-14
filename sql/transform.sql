-- ===========================================================================
-- transform.sql  —  STAGING → MARTS. All the analytics logic lives here, in SQL.
--
-- Techniques shown (each numbered block is its own README row):
--   1. CTE chain + LAG window            -> month-over-month revenue
--   2. Window frame ROWS BETWEEN         -> 3-month and 12-month rolling avg
--   3. RANK() OVER (PARTITION BY month)  -> top regions per month
--   4. ROW_NUMBER() dedup                -> one row per order at grain
--   5. Gaps and islands (ROW_NUMBER diff)-> customer order streaks / gaps
--   6. Conditional aggregation + CTE     -> cohort / channel mix
--   7. Anti-join data validation         -> orders with no items (DQ)
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- Clean base: dedupe orders at grain FIRST (defect 2: double-loaded copies).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_orders_clean AS
WITH numbered AS (
    SELECT
        order_id, customer_id, order_date, channel, status,
        ROW_NUMBER() OVER (
            PARTITION BY order_id, customer_id, order_date, channel, status
            ORDER BY order_id
        ) AS rn
    FROM fact_orders
)
SELECT order_id, customer_id, order_date, channel, status
FROM numbered
WHERE rn = 1;

-- Revenue line grain: join items to the cleaned header, exclude non-completed.
CREATE OR REPLACE VIEW v_revenue_lines AS
SELECT
    o.order_id,
    o.customer_id,
    o.order_date,
    o.channel,
    c.region,
    i.product_id,
    p.category,
    i.quantity,
    i.unit_price,
    (i.quantity * i.unit_price) AS line_revenue
FROM v_orders_clean o
JOIN fact_order_items i ON i.order_id = o.order_id
JOIN dim_customer  c     ON c.customer_id = o.customer_id
JOIN dim_product   p     ON p.product_id = i.product_id
WHERE o.status = 'completed';

-- ---------------------------------------------------------------------------
-- 1 + 2. Monthly revenue with MoM % (LAG) and rolling windows (frame).
-- ---------------------------------------------------------------------------
DELETE FROM mart_monthly_revenue;
INSERT INTO mart_monthly_revenue
WITH monthly AS (
    SELECT
        DATE_TRUNC('month', order_date) AS month_key,
        COUNT(DISTINCT order_id)        AS orders,
        SUM(quantity)                   AS units,
        SUM(line_revenue)               AS revenue
    FROM v_revenue_lines
    GROUP BY 1
),
with_lag AS (
    SELECT
        month_key, orders, units, revenue,
        LAG(revenue) OVER (ORDER BY month_key) AS prev_revenue,
        AVG(revenue) OVER (
            ORDER BY month_key
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ) AS rolling_3m,
        AVG(revenue) OVER (
            ORDER BY month_key
            ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
        ) AS rolling_12m
    FROM monthly
)
SELECT
    month_key,
    orders,
    units,
    revenue,
    prev_revenue,
    CASE WHEN prev_revenue IS NULL OR prev_revenue = 0 THEN NULL
         ELSE ROUND((revenue - prev_revenue) / prev_revenue * 100, 2) END AS mom_pct,
    ROUND(rolling_3m, 2)  AS rolling_3m,
    ROUND(rolling_12m, 2) AS rolling_12m
FROM with_lag
ORDER BY month_key;

-- ---------------------------------------------------------------------------
-- 3. Top regions per month (RANK within partition).
-- ---------------------------------------------------------------------------
DELETE FROM mart_region_rank;
INSERT INTO mart_region_rank
WITH region_month AS (
    SELECT
        DATE_TRUNC('month', order_date) AS month_key,
        region,
        SUM(line_revenue) AS revenue
    FROM v_revenue_lines
    WHERE region IS NOT NULL AND region <> ''
    GROUP BY 1, 2
)
SELECT
    month_key, region, revenue,
    RANK() OVER (PARTITION BY month_key ORDER BY revenue DESC) AS rank_in_month
FROM region_month
ORDER BY month_key, rank_in_month;

-- ---------------------------------------------------------------------------
-- 4 + 5. Customer value, order gaps, and recency rank.
--    gap_days uses LAG over the customer's own order sequence.
--    recency_rank shows ROW_NUMBER as a stable tie-break.
-- ---------------------------------------------------------------------------
DELETE FROM mart_customer_orders;
INSERT INTO mart_customer_orders
WITH per_order AS (
    SELECT
        customer_id,
        order_date,
        LAG(order_date) OVER (
            PARTITION BY customer_id ORDER BY order_date
        ) AS prev_order_date
    FROM (SELECT DISTINCT customer_id, order_id, order_date FROM v_revenue_lines)
),
agg AS (
    SELECT
        customer_id,
        MIN(order_date) AS first_order,
        MAX(order_date) AS last_order,
        COUNT(*)        AS order_count
    FROM (SELECT DISTINCT customer_id, order_id, order_date FROM v_revenue_lines)
    GROUP BY customer_id
),
revenue AS (
    SELECT customer_id, SUM(line_revenue) AS total_revenue
    FROM v_revenue_lines GROUP BY customer_id
),
last_gap AS (
    SELECT customer_id,
           MAX(order_date - prev_order_date) AS gap_days
    FROM per_order
    WHERE prev_order_date IS NOT NULL
    GROUP BY customer_id
)
SELECT
    a.customer_id,
    c.customer_name,
    c.region,
    a.first_order,
    a.last_order,
    a.order_count,
    r.total_revenue,
    g.gap_days,
    ROW_NUMBER() OVER (ORDER BY r.total_revenue DESC, a.customer_id) AS recency_rank
FROM agg a
JOIN dim_customer c ON c.customer_id = a.customer_id
JOIN revenue r      ON r.customer_id = a.customer_id
LEFT JOIN last_gap g ON g.customer_id = a.customer_id
ORDER BY recency_rank;

-- ---------------------------------------------------------------------------
-- 6. Channel mix via conditional aggregation (single pass, no subquery per
--    channel). month_key x channel -> pivot columns.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE mart_channel_mix AS
SELECT
    DATE_TRUNC('month', order_date) AS month_key,
    ROUND(SUM(CASE WHEN channel = 'web'   THEN line_revenue ELSE 0 END), 2) AS web,
    ROUND(SUM(CASE WHEN channel = 'app'   THEN line_revenue ELSE 0 END), 2) AS app,
    ROUND(SUM(CASE WHEN channel = 'store' THEN line_revenue ELSE 0 END), 2) AS store,
    ROUND(SUM(CASE WHEN channel = 'phone' THEN line_revenue ELSE 0 END), 2) AS phone,
    ROUND(SUM(line_revenue), 2) AS total
FROM v_revenue_lines
GROUP BY 1
ORDER BY 1;

-- ---------------------------------------------------------------------------
-- 7. Data-quality checks, written as SQL so they run anywhere.
-- ---------------------------------------------------------------------------
DELETE FROM dq_issues;

INSERT INTO dq_issues
-- header-only orders: an order with no line items (defect 1)
SELECT 'orders_without_items', 'high',
       'Orders present in the header but absent from fact_order_items',
       COUNT(*)
FROM v_orders_clean o
WHERE NOT EXISTS (SELECT 1 FROM fact_order_items i WHERE i.order_id = o.order_id);

INSERT INTO dq_issues
-- duplicate order copies in the raw load (defect 2)
SELECT 'duplicate_order_rows', 'medium',
       'Raw order rows that are exact duplicates of another row',
       COUNT(*)
FROM (
    SELECT order_id FROM fact_orders
    GROUP BY order_id, customer_id, order_date, channel, status
    HAVING COUNT(*) > 1
);

INSERT INTO dq_issues
-- orphan foreign keys: items pointing at a missing order
SELECT 'orphan_order_items', 'high',
       'fact_order_items rows whose order_id is not in fact_orders',
       COUNT(*)
FROM fact_order_items i
WHERE NOT EXISTS (SELECT 1 FROM fact_orders o WHERE o.order_id = i.order_id);

INSERT INTO dq_issues
-- missing region on the customer dimension
SELECT 'customers_missing_region', 'low',
       'Customers with no region (breaks any regional cut)',
       COUNT(*)
FROM dim_customer
WHERE region IS NULL OR region = '';
