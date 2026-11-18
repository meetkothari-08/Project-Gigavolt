# Deployment

## Layout

The system ran on AWS EC2 (Ubuntu) as two application servers, plus the database tier:

| Server | Runs | Install |
|---|---|---|
| **Vector / document server** | ChromaDB HTTP server `:8000`, embedding API `:8001`, document ingestion trigger `:8002`, `04-vector-search/scripts/` corpus build | `pip install -e ".[ml]"` |
| **RAG server** | `gigavolt-ask`, relational ingestion, benchmark, Ollama `:11434` with `phi` | `pip install -e .` |
| **Database tier** | MariaDB (Silver schema; 3-node Galera for HA), MongoDB (telemetry) | see below |

Every endpoint is configured through environment variables (see [`.env.example`](../.env.example)), so the same code also runs on a single machine with everything on `127.0.0.1`.

## 1. Python environment

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # RAG server
pip install -e ".[dev,ml]"       # vector / document server
cp .env.example .env             # then fill in credentials and hosts
```

## 2. MariaDB

```bash
# Schema, functions, audit log, generated column, triggers, procedure, view
scripts/deploy_database.sh

# Build Bronze -> staging -> quarantine -> Silver from the raw CSVs, then run all 46 checks
# (needs local_infile=1 on the server)
scripts/deploy_database.sh --raw-dir data/raw/erp --validate

# Alternatively, restore an existing Silver layer from a data-only seed
mariadb-dump --no-create-info --skip-triggers --complete-insert gigavolt \
    customers equipment_models equipment parts dispatches warranty_claims > silver_seed.sql
scripts/deploy_database.sh --seed silver_seed.sql --validate
```

To reconcile a rebuild with a reference copy (for example, production restored into `gigavolt_prod`):

```bash
python 01-data-ingestion/tools/compare_silver.py --candidate gigavolt --reference gigavolt_prod --apply-fixes
```

Create a read-only application account (the grants are listed in [`02-sql-automation/sql/05_security_views.sql`](../02-sql-automation/sql/05_security_views.sql)) and put it in `MARIADB_USER` / `MARIADB_PASSWORD`. The relational pipeline and the RAG retriever only ever need `SELECT`.

## 3. MongoDB

Load the telemetry JSON into `sensorDB.telemetry` and create the indexes the retriever relies on:

```bash
mongoimport --db sensorDB --collection telemetry --file data/raw/telemetry/telemetry_data.json
mongosh sensorDB --eval '
  db.telemetry.createIndex({equipment_id: 1, timestamp: -1});
  db.telemetry.createIndex({fault_code: 1});
  db.telemetry.createIndex({model: 1});'
```

## 4. Vector store (vector / document server)

```bash
export GIGAVOLT_DOCUMENTS_DIR=data/documents   # the technical PDFs
python 04-vector-search/scripts/extract_and_chunk.py
python 04-vector-search/scripts/validate_chunks.py
python 04-vector-search/scripts/rebuild_chroma_from_chunks.py    # or steps 3-5 through MariaDB Vector

sudo cp 06-automation/deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gigavolt-chroma gigavolt-embedding-api gigavolt-ingestion-api
curl -s localhost:8001/health
```

New or changed PDFs dropped into the documents folder are picked up by:

```bash
gigavolt-ingest-documents --apply
# or remotely:
curl -X POST -H "X-API-Key: $M6_API_KEY" http://<vector-server>:8002/run
```

## 5. RAG server

```bash
ollama pull phi
gigavolt-ingest-relational --dry-run        # check DB connectivity and validation
gigavolt-ingest-relational
gigavolt-ask "Show the service history and warranty claims for EQ-5508"
python 06-automation/benchmark/rag_benchmark.py
```

## Data

Source datasets are not committed. Place them under `data/` (gitignored):

```
data/
├── raw/erp/{customers,equipment,dispatches,parts,warranty_claims}.csv
├── raw/telemetry/telemetry_data.json
├── documents/*.pdf
├── processed/            # written by 04-vector-search/scripts
└── chroma_store/         # written by 04-vector-search/scripts and the document pipeline
```

## Security notes

* No credentials live in code. Everything comes from the environment or a `.env` file, which is gitignored.
* The application database account is read-only; customer PII is exposed only through `vw_Customer_Safe`.
* `Audit_Logs` rejects `UPDATE` and `DELETE` at the trigger level.
* The ingestion trigger requires an API key, compared in constant time. Keep ports 8000–8002 inside the VPC security group.
