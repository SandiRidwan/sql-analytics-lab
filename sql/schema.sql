-- ===========================================================================
-- schema.sql  —  star schema for the analytics lab (DuckDB dialect).
-- The PostgreSQL and T-SQL ports of the same tables live in sql/postgres/ and
-- sql/tsql/. This file is the canonical shape.
-- ===========================================================================

CREATE OR REPLACE TABLE dim_customer (
    customer_id   INTEGER PRIMARY KEY,
    customer_name VARCHAR,
    region        VARCHAR,
    segment       VARCHAR,
    joined_at     DATE
);

CREATE OR REPLACE TABLE dim_product (
    product_id INTEGER PRIMARY KEY,
    sku        VARCHAR,
    category   VARCHAR,
    list_price DECIMAL(10,2),
    is_active  BOOLEAN
);

CREATE OR REPLACE TABLE dim_date (
    date_key   DATE PRIMARY KEY,
    year       INTEGER,
    quarter    INTEGER,
    month      INTEGER,
    iso_week   INTEGER,
    weekday    VARCHAR,
    is_weekend BOOLEAN
);

-- Order header. NOTE: order_id is NOT unique on purpose — the raw load contains
-- duplicate copies, so every consumer must dedupe at this grain.
CREATE OR REPLACE TABLE fact_orders (
    order_id    INTEGER,
    customer_id INTEGER,
    order_date  DATE,
    channel     VARCHAR,
    status      VARCHAR
);

CREATE OR REPLACE TABLE fact_order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER,
    product_id    INTEGER,
    quantity      INTEGER,
    unit_price    DECIMAL(10,2)
);

-- Analytical marts, written by transform.sql
CREATE OR REPLACE TABLE mart_monthly_revenue (
    month_key   DATE,
    orders      BIGINT,
    units       BIGINT,
    revenue     DECIMAL(14,2),
    prev_revenue DECIMAL(14,2),
    mom_pct     DOUBLE,
    rolling_3m  DOUBLE,
    rolling_12m DOUBLE
);

CREATE OR REPLACE TABLE mart_region_rank (
    month_key    DATE,
    region       VARCHAR,
    revenue      DECIMAL(14,2),
    rank_in_month BIGINT
);

CREATE OR REPLACE TABLE mart_customer_orders (
    customer_id   INTEGER,
    customer_name VARCHAR,
    region        VARCHAR,
    first_order   DATE,
    last_order    DATE,
    order_count   BIGINT,
    total_revenue DECIMAL(14,2),
    gap_days      BIGINT,
    recency_rank  BIGINT
);

CREATE OR REPLACE TABLE dq_issues (
    check_name VARCHAR,
    severity   VARCHAR,
    detail     VARCHAR,
    bad_rows   BIGINT
);
