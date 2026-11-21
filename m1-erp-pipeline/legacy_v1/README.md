# Legacy v1: first ingestion and cleansing pipeline

The first version of the ERP pipeline, kept as written apart from comment tidying and a redacted password. It builds a separate database (`gigavolt_erp`) with its own schema and is **not** used by the rest of the system. The current pipeline is [`../sql/`](../sql/) (run with `scripts/deploy_database.sh --raw-dir`).

| File | Purpose |
|---|---|
| `01_staging_schema.sql` | `import_*` staging tables: every column `TEXT`, MyISAM, with a `stg_row_id` lineage key |
| `02_load.sql` | `LOAD DATA LOCAL INFILE` from `/tmp/data/*.csv` (CRLF-aware) |
| `03_clean.sql` | In-place cleansing with the `cx()` (tag, space and null-token scrub) and `nd()` (five-format date) functions, phone, money and status normalization |
| `04_prod_schema.sql` | 3NF schema: `locations`, `equipment_models`, `customers`, `equipment_units`, `service_logs`, `parts_inventory`, `warranty_claims`, and the `rejected_dispatches` quarantine |
| `05_transform_load.sql` | Dedup (first row wins), orphan quarantine, and `INSERT … SELECT` into the 3NF tables |
| `06_validate.sql` | Row counts against expected values, and orphan counts for 7 relationships |
| `07_app_user.sql` | Application account (the password is a placeholder) |

Re-run on the raw extracts (MariaDB 10.11), this pipeline still produces the expected counts (500 customers, 473 locations, 5 models, 2,500 units, 4,941 service logs, 59 rejected dispatches, 150 parts, 1,200 claims) with 0 orphaned foreign keys.

**What changed in the current pipeline**

* Bronze, staging and quarantine tables now live in the same database as Silver and are linked by `bronze_row_id`.
* `cx()` and `nd()` became `clean_text()`, `clean_date()` and `clean_money()` in `sql/04_cleansing_functions.sql`, with unit tests in `validation/validate_cleansing_functions.sql`. Carriage returns are now stripped as well.
* Duplicates keep the most recent row instead of the first.
* Statuses are stored upper-case, model voltage keeps its unit (`480V`), and city and state stay on `customers` instead of moving to a `locations` table.
* Warranty claims log every nulled dangling reference in `warranty_claims_quarantine`.
