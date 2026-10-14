<div align="center">

<img src="https://readme-typing-svg.demolab.com?font=Orbitron&weight=900&size=34&duration=3000&pause=1000&color=0F766E&center=true&vCenter=true&width=940&height=70&lines=SQL+ANALYTICS+LAB" alt="SQL Analytics Lab" />

![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-336791?style=for-the-badge&logo=postgresql&logoColor=white)
![SQL Server](https://img.shields.io/badge/SQL_Server-T--SQL-CC2927?style=for-the-badge&logo=microsoftsqlserver&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-OLAP-FFF000?style=for-the-badge&logo=duckdb&logoColor=black)
![Python](https://img.shields.io/badge/Python-3.10+-1F5C3D?style=for-the-badge&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-0D1117?style=for-the-badge)

</div>

---

## 🧮 What this is

An **SQL analytics lab that actually runs** — not a folder of queries on paper.
Every technique is executed against **real databases** (PostgreSQL 18 and
Microsoft SQL Server), measured, and reported honestly.

It focuses on the three things a Data Analyst job always tests:

1. **Advanced SQL** — CTEs, window functions (`LAG`, `RANK`, `ROW_NUMBER`),
   conditional aggregation, joins at the right grain.
2. **Query performance tuning** — the same query written two ways, with
   **`EXPLAIN ANALYZE` before and after** and measured timings.
3. **Data quality** — finding duplicates, orphans and header-only orders in SQL,
   then fixing them.

To prove the tuning is real (not engine noise), the benchmark runs on
**PostgreSQL row-store**, where an index and a rewrite genuinely change the plan.

```bash
python src/generate_data.py     # synthetic data + 3 deliberate defects
python src/load_db.py           # -> DuckDB
python src/run_transform.py     # marts: MoM, rolling, rank, dedup, DQ
python src/pg_lab.py            # before/after tuning on PostgreSQL
python src/tsql_lab.py          # 8 T-SQL queries on SQL Server
python tests/test_data_quality.py
```

---

## ⚡ Query tuning — measured numbers (PostgreSQL)

Same query, two forms. Time = median of 5 runs. Full plans in `reports/plans/`.

| Case | Before | After | Speedup | Fix |
|---|---:|---:|---:|---|
| **1. Function on a column (SARGability)** | 35.66 ms | 25.74 ms | **1.39×** | `YEAR(col)=n` → `col >= a AND col < b` + index |
| **2. Recompute vs pre-aggregated table** | 103.98 ms | 0.22 ms | **472×** | repeated JOIN+GROUP BY → materialized view |
| **3. Correlated subquery per row** | 8837.30 ms | 157.69 ms | **56×** | per-row subquery → single grouped LEFT JOIN |

> **Why** — "query performance improvement" is an explicit requirement in most
> analyst specs, and it is almost never demonstrated.
> **Goal** — show that the queries are not only correct but fast, and measure the
> difference.
> **Impact** — a correlated subquery per row takes a report from 8.8 s to 0.16 s;
> the difference between a dashboard that "feels broken" and one that is responsive.

**The plan shape changes, not just the time.** See
`reports/plans/3._Correlated_before.txt` (Nested Loop + Seq Scan per row) vs
`..._after.txt` (a single Hash Join). A number without a plan is an anecdote;
both are committed here.

---

## 🧠 What each query demonstrates

| # | Question | Technique | Dialect | Where |
|---|---|---|---|---|
| 1 | Month-over-month revenue growth | CTE + `LAG()` | PG · T-SQL · DuckDB | `sql/transform.sql` · Q1 |
| 2 | 12-month rolling average | window frame `ROWS BETWEEN` | all three | Q2 |
| 3 | Top-3 regions per month | `RANK()`/`ROW_NUMBER()` within a partition | all three | Q3 |
| 4 | De-duplicate orders at the grain | `ROW_NUMBER()` dedup | all three | Q4 |
| 5 | Gaps between a customer's orders | gaps-and-islands (`LAG` + `DATEDIFF`) | all three | Q5 |
| 6 | Channel mix per month | conditional aggregation (single-pass pivot) | all three | Q6 |
| 7 | Orders with no line items | anti-join (`NOT EXISTS`) | all three | Q7 |
| 8 | Running total per customer | `SUM() OVER (... ROWS UNBOUNDED PRECEDING)` | T-SQL | Q8 |

Every query lives in **three places** and is actually executed:
`sql/transform.sql` (DuckDB), `src/pg_lab.py` (PostgreSQL), `src/tsql_lab.py` (T-SQL).

---

## 🗄️ Schema

A small star schema with **three deliberately injected defects**, because the
interesting SQL is the SQL that finds and fixes problems:

```
dim_customer ─┐
dim_product  ─┼─◄ fact_orders ──1:*── fact_order_items
dim_date     ─┘

Injected defects:
  1. header-only orders (no line items)   -> found by anti-join
  2. duplicated orders (double-load)      -> dedup at the grain
  3. customers with no region             -> null validation
```

| Table | Rows | Note |
|---|---:|---|
| `dim_customer` | 5,000 | 1.5% missing region (on purpose) |
| `dim_product` | 400 | 6 categories |
| `fact_orders` | 60,720 | 720 duplicates (on purpose) |
| `fact_order_items` | 146,990 | unique PK |
| `dim_date` | 791 | 2-year calendar |

---

## 🧪 Data quality — what the SQL found (not the eye)

The `dq_issues` table is filled by `sql/transform.sql`, shown by
`src/run_transform.py`:

| Check | Severity | Bad rows |
|---|---|---:|
| `orders_without_items` | high | 1,188 |
| `duplicate_order_rows` | medium | 720 |
| `customers_missing_region` | low | 90 |
| `orphan_order_items` | high | 0 |

Each check is a single SQL statement that can be scheduled; the result is not just
a count but the list of offending rows to act on.

---

## ✅ Quality — 11 automated tests

```
PASS  raw data contains the injected defects
PASS  v_orders_clean returns one row per order_id after dedup
PASS  no orphan line items
PASS  header-only orders detected (> 0)
PASS  reported duplicate count == raw count
PASS  revenue is never negative
PASS  first-month mom_pct is NULL (not 0 or inf)
PASS  first-month rolling_12m equals its own value
PASS  region rank starts at 1 every month
PASS  recency_rank is dense 1..n
PASS  channel pivot columns sum to the row total
```

The tests verify **analytical correctness**, not that files exist — including
invariants (pivot == total) and edges (first month is `NULL`, not zero).

---

## 📁 Structure

```
sql-analytics-lab/
├── src/
│   ├── config.py            # paths + connection (single source of truth)
│   ├── generate_data.py     # deterministic synthetic data + 3 defects
│   ├── load_db.py           # CSV -> DuckDB
│   ├── run_transform.py     # run transform.sql, print the marts
│   ├── pg_lab.py            # * before/after tuning on PostgreSQL
│   └── tsql_lab.py          # * 8 T-SQL queries on SQL Server
├── sql/
│   ├── schema.sql           # star schema (canonical)
│   └── transform.sql        # 7 analytics blocks in pure SQL
├── tests/test_data_quality.py   # 11 tests (data + invariants)
├── data/{raw,analytics.duckdb}  # rebuilt, not committed
├── reports/
│   ├── plans/               # EXPLAIN ANALYZE before/after
│   └── tables/              # query results + timing CSV
└── docs/
```

---

## 🚀 Quick Start

```bash
pip install -r requirements.txt

# 1) DuckDB path — no server needed
python src/generate_data.py
python src/load_db.py
python src/run_transform.py

# 2) PostgreSQL tuning (needs a running PostgreSQL)
#    set PGPASSWORD / PGUSER if different
python src/pg_lab.py

# 3) T-SQL on SQL Server (needs SQL Server + ODBC Driver 17)
python src/tsql_lab.py

# 4) Tests
python tests/test_data_quality.py
```

Connection is configured through environment variables: `PGHOST`, `PGPORT`,
`PGUSER`, `PGPASSWORD`, `SQLSERVER`. No credentials are stored in the repo.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Advanced SQL** | PostgreSQL 18 · T-SQL (SQL Server 2017) · DuckDB |
| **Tuning** | `EXPLAIN (ANALYZE, BUFFERS)` · indexes · materialized view |
| **Python** | stdlib + `psycopg2` + `pyodbc` (orchestration, not a SQL substitute) |
| **Data** | deterministic synthetic (fixed seed, reproducible) |
| **Tests** | `unittest` (11 analytical-invariant tests) |

---

## ⚠️ Limitations (honest)

- **Synthetic data.** The transaction values are not real; what is real is the
  *schema, the techniques, and the measured tuning*. Scale is small (60k orders) so
  it runs locally — real speedups differ at TB scale.
- **The 1.39× on case 1 is small** because the dataset is small; the SARGability
  effect grows with volume. The number is reported as-is, not rounded up.
- **Not a substitute for production experience.** This is evidence that the
  techniques are known and measured, not a claim of having run a company warehouse.

---

## 👤 Author

<div align="center">

**Sandi Ridwan** — Data Automation Engineer · Web Scraping Specialist · SQL & Analytics

📍 Palu, Central Sulawesi, Indonesia

[![Upwork](https://img.shields.io/badge/Upwork-Hire_Me-0F766E?style=for-the-badge&logo=upwork&logoColor=white)](https://www.upwork.com/freelancers/~011f6d0fbb4a372974)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0077B5?style=for-the-badge&logo=linkedin&logoColor=white)](https://linkedin.com/in/sandi-ridwan)
[![GitHub](https://img.shields.io/badge/GitHub-Follow-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/SandiRidwan)

</div>

## 📄 License

MIT — synthetic dataset, built for portfolio and learning.
