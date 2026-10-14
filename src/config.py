"""Central config: paths and default connection settings."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
DUCKDB_FILE = DATA / "analytics.duckdb"
SQL_DIR = ROOT / "sql"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
TABLES = REPORTS / "tables"
PLANS = REPORTS / "plans"

# Deterministic seed so the README numbers reproduce exactly
SEED = 20261014

# PostgreSQL lab
PG = {
    "host": os.environ.get("PGHOST", "localhost"),
    "port": int(os.environ.get("PGPORT", "5432")),
    "user": os.environ.get("PGUSER", "postgres"),
    "password": os.environ.get("PGPASSWORD", "postgres"),
    "dbname": "sql_lab",
}

# SQL Server lab
SQLSERVER = os.environ.get("SQLSERVER", "localhost")
SQLSERVER_DB = "SqlLab"
