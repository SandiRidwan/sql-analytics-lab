<div align="center">

<img src="https://readme-typing-svg.demolab.com?font=Orbitron&weight=900&size=34&duration=3000&pause=1000&color=0F766E&center=true&vCenter=true&width=940&height=70&lines=SQL+ANALYTICS+LAB" alt="SQL Analytics Lab" />

![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-336791?style=for-the-badge&logo=postgresql&logoColor=white)
![SQL Server](https://img.shields.io/badge/SQL_Server-T--SQL-CC2927?style=for-the-badge&logo=microsoftsqlserver&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-OLAP-FFF000?style=for-the-badge&logo=duckdb&logoColor=black)
![Python](https://img.shields.io/badge/Python-3.10+-1F5C3D?style=for-the-badge&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-0D1117?style=for-the-badge)

</div>

---

## 🧮 Apa ini?

**Lab SQL analitik yang benar-benar dijalankan** — bukan kumpulan query di atas
kertas. Setiap teknik dikerjakan pada **database sungguhan** (PostgreSQL 18 dan
Microsoft SQL Server), diukur, dan hasilnya dilaporkan apa adanya.

Fokusnya tiga hal yang selalu diuji di peran Data Analyst:

1. **Advanced SQL** — CTE, window functions (`LAG`, `RANK`, `ROW_NUMBER`),
   agregasi bersyarat, joins pada grain.
2. **Query performance tuning** — query yang sama, dua cara, dengan **EXPLAIN
   ANALYZE** sebelum/sesudah dan waktu terukur.
3. **Data quality** — menemukan duplikat, baris yatim, dan order tanpa item,
   dalam SQL, lalu memperbaikinya.

Untuk membuktikan tuning itu nyata (bukan derau engine embedded), benchmark
dijalankan di **PostgreSQL row-store**, tempat index dan rewrite benar-benar
mengubah rencana eksekusi.

```bash
python src/generate_data.py     # data sintetis + 3 cacat yang disengaja
python src/load_db.py           # → DuckDB
python src/run_transform.py     # marts: MoM, rolling, rank, dedup, DQ
python src/pg_lab.py            # tuning sebelum/sesudah di PostgreSQL
python src/tsql_lab.py          # 8 query T-SQL di SQL Server
python tests/test_data_quality.py
```

---

## ⚡ Query tuning — angka terukur (PostgreSQL)

Query yang sama, dua bentuk. Waktu = median 5 run. Rencana lengkap di
`reports/plans/`.

| Kasus | Sebelum | Sesudah | Speedup | Perbaikan |
|---|---:|---:|---:|---|
| **1. Fungsi pada kolom (SARGability)** | 35.66 ms | 25.74 ms | **1.39×** | `YEAR(col)=n` → `col >= a AND col < b` + index |
| **2. Hitung ulang vs tabel pra-agregat** | 103.98 ms | 0.22 ms | **472×** | JOIN+GROUP BY berulang → materialized view |
| **3. Subquery berkorelasi per baris** | 8837.30 ms | 157.69 ms | **56×** | subquery per baris → satu grouped LEFT JOIN |

> **Kenapa** — "query performance improvement" adalah syarat eksplisit di banyak
> lowongan, dan paling sering tidak dibuktikan.
> **Tujuan** — menunjukkan bukan sekadar bisa menulis query, tapi bisa membuatnya
> cepat, dan mengukur perbedaannya.
> **Dampak** — subquery berkorelasi per baris menjatuhkan laporan dari 8,8 s ke 0,16 s;
> perbedaan antara dashboard yang "terasa rusak" dan yang responsif.

**Bentuk rencana berubah, bukan cuma waktunya.** Lihat
`reports/plans/3._Correlated_before.txt` (Nested Loop + Seq Scan per baris) vs
`..._after.txt` (satu Hash Join). Angka tanpa rencana hanyalah anekdot; keduanya
disimpan.

---

## 🧠 Apa yang ditunjukkan setiap query

| # | Pertanyaan | Teknik | Dialek | Berkas |
|---|---|---|---|---|
| 1 | Pertumbuhan pendapatan bulan-ke-bulan | CTE + `LAG()` | PG · T-SQL · DuckDB | `sql/transform.sql` · Q1 |
| 2 | Rata-rata bergulir 12 bulan | window frame `ROWS BETWEEN` | ketiganya | Q2 |
| 3 | Top-3 region per bulan | `RANK()`/`ROW_NUMBER()` per partisi | ketiganya | Q3 |
| 4 | Dedup order pada grain | `ROW_NUMBER()` dedup | ketiganya | Q4 |
| 5 | Jeda antar-order pelanggan | gaps & islands (`LAG` + `DATEDIFF`) | ketiganya | Q5 |
| 6 | Bauran kanal per bulan | agregasi bersyarat (pivot satu pass) | ketiganya | Q6 |
| 7 | Order tanpa line item | anti-join (`NOT EXISTS`) | ketiganya | Q7 |
| 8 | Running total per pelanggan | `SUM() OVER (... ROWS UNBOUNDED PRECEDING)` | T-SQL | Q8 |

Setiap query ada di **tiga tempat** dan dijalankan sungguhan: `sql/transform.sql`
(DuckDB), `src/pg_lab.py` (PostgreSQL), `src/tsql_lab.py` (T-SQL).

---

## 🗄️ Skema

Star schema kecil dengan **tiga cacat yang sengaja ditanam**, karena SQL yang
menarik adalah SQL yang menemukan dan memperbaiki masalah:

```
dim_customer ─┐
dim_product  ─┼─◄ fact_orders ──1:*── fact_order_items
dim_date     ─┘

Cacat yang ditanam:
  1. order tanpa line item (header-only)        → deteksi anti-join
  2. order terduplikasi (double-load)            → dedup pada grain
  3. pelanggan tanpa region                      → validasi null
```

| Tabel | Baris | Catatan |
|---|---:|---|
| `dim_customer` | 5.000 | 1,5% tanpa region (sengaja) |
| `dim_product` | 400 | 6 kategori |
| `fact_orders` | 60.720 | 720 duplikat (sengaja) |
| `fact_order_items` | 146.990 | PK unik |
| `dim_date` | 791 | kalender 2 tahun |

---

## 🧪 Data quality — apa yang ditemukan (SQL, bukan mata)

`dq_issues` diisi oleh `sql/transform.sql`, ditampilkan via `src/run_transform.py`:

| Pemeriksaan | Severity | Baris buruk |
|---|---|---:|
| `orders_without_items` | high | 1.188 |
| `duplicate_order_rows` | medium | 720 |
| `customers_missing_region` | low | 90 |
| `orphan_order_items` | high | 0 |

Setiap pemeriksaan adalah satu pernyataan SQL yang bisa dijadwalkan; hasilnya
bukan hanya angka, tapi **daftar baris yang bermasalah** untuk ditindak.

---

## ✅ Kualitas — 11 uji otomatis

```
PASS  raw punya cacat yang disuntikkan (duplikat ada)
PASS  v_orders_clean → satu baris per order_id setelah dedup
PASS  tidak ada order_item yatim
PASS  order tanpa item terdeteksi > 0
PASS  jumlah duplikat yang dilaporkan == jumlah mentah
PASS  revenue tidak pernah negatif
PASS  mom_pct bulan pertama = NULL (bukan 0 atau inf)
PASS  rolling_12m bulan pertama = nilainya sendiri
PASS  rank region mulai dari 1 tiap bulan
PASS  recency_rank rapat 1..n
PASS  kolom pivot kanal berjumlah sama dengan total
```

Uji memverifikasi **kebenaran analitik**, bukan sekadar "file ada" — termasuk
invarian (pivot == total) dan tepi (bulan pertama `NULL`, bukan nol).

---

## 📁 Struktur

```
sql-analytics-lab/
├── src/
│   ├── config.py            # path + koneksi (satu sumber kebenaran)
│   ├── generate_data.py     # data sintetis deterministik + 3 cacat
│   ├── load_db.py           # CSV → DuckDB
│   ├── run_transform.py     # jalankan transform.sql, tampilkan marts
│   ├── pg_lab.py            # ★ tuning sebelum/sesudah di PostgreSQL
│   └── tsql_lab.py          # ★ 8 query T-SQL di SQL Server
├── sql/
│   ├── schema.sql           # star schema (kanonik)
│   └── transform.sql        # 7 blok analytics dalam SQL murni
├── tests/test_data_quality.py   # 11 uji (data + invarian)
├── data/{raw,analytics.duckdb}  # dibangun ulang, tidak di-commit
├── reports/
│   ├── plans/               # EXPLAIN ANALYZE sebelum/sesudah
│   └── tables/              # hasil query + timing CSV
└── docs/
```

---

## 🚀 Quick Start

```bash
pip install -r requirements.txt

# 1) Jalur DuckDB — tanpa server
python src/generate_data.py
python src/load_db.py
python src/run_transform.py

# 2) Tuning PostgreSQL (butuh PostgreSQL berjalan)
#    set PGPASSWORD / PGUSER bila berbeda
python src/pg_lab.py

# 3) T-SQL di SQL Server (butuh SQL Server + ODBC Driver 17)
python src/tsql_lab.py

# 4) Uji
python tests/test_data_quality.py
```

Konfigurasi koneksi lewat environment variable: `PGHOST`, `PGPORT`, `PGUSER`,
`PGPASSWORD`, `SQLSERVER`. Tidak ada kredensial yang disimpan di repo.

---

## 🛠️ Tech Stack

| Layer | Teknologi |
|---|---|
| **Advanced SQL** | PostgreSQL 18 · T-SQL (SQL Server 2017) · DuckDB |
| **Tuning** | `EXPLAIN (ANALYZE, BUFFERS)` · index · materialized view |
| **Python** | stdlib + `psycopg2` + `pyodbc` (orkestrasi, bukan pengganti SQL) |
| **Data** | sintetis deterministik (seed tetap, dapat direproduksi) |
| **Uji** | `unittest` (11 uji invarian analitik) |

---

## ⚠️ Keterbatasan (jujur)

- **Data sintetis.** Angka transaksinya tidak nyata; yang nyata adalah *skema,
  teknik, dan pengukuran tuning*. Skala kecil (60rb order) agar bisa dijalankan
  lokal — speedup nyata akan berbeda pada skala TB.
- **Speedup 1,39× di kasus 1 kecil** karena dataset kecil; efek SARGability
  membesar seiring volume. Angka dilaporkan apa adanya, tidak dibulatkan ke atas.
- **Bukan pengganti pengalaman produksi.** Ini bukti bahwa tekniknya dikuasai
  dan diukur, bukan klaim pernah menangani warehouse perusahaan.

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

MIT — dataset sintetis, dibuat untuk portofolio dan pembelajaran.
