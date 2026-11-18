<div align="center">

# ⚡ Gigavolt

**Multi-model data platform and hybrid RAG engine for battery field service**

[![CI](https://github.com/meetkothari-08/Project-Gigavolt/actions/workflows/ci.yml/badge.svg)](https://github.com/meetkothari-08/Project-Gigavolt/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![MariaDB](https://img.shields.io/badge/MariaDB-Galera%20%7C%20ColumnStore-003545?logo=mariadb&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-telemetry-47A248?logo=mongodb&logoColor=white)
![ChromaDB](https://img.shields.io/badge/ChromaDB-HNSW-FF6F61)
![Ollama](https://img.shields.io/badge/Ollama-Phi-000000?logo=ollama&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-EC2%20%2B%20EBS-FF9900?logo=amazonwebservices&logoColor=white)

</div>

Gigavolt turns messy ERP extracts, technical PDFs and battery telemetry into a question-answering system for field engineers. Each data type lands in the store built for it: **MariaDB** for relational ERP data, **ChromaDB** for semantic document search, **MongoDB** for telemetry. Incremental pipelines keep all three current, and a local LLM answers questions with citations that are checked against the evidence it retrieved.

> *"Show the service history for EQ-5508 and what the manual says about over-temperature alarms."*
> → equipment, dispatch and warranty records (MariaDB) + recent readings and faults (MongoDB) + manual passages (ChromaDB) → cited answer → citation check

<p align="center"><img src="docs/architecture.svg" alt="Gigavolt architecture" width="100%"></p>

## Milestones

| # | Milestone | What was built | Headline result |
|:-:|---|---|---|
| 1 | [**Data Ingestion & Lakehouse**](01-data-ingestion/) | Bronze → staging → quarantine → 3NF Silver in SQL, unit-tested cleansing functions, raw-data profiler | 9,498 raw → 9,296 clean rows, **0 orphaned FKs**; rebuild matches production on **99.993%** of cells |
| 2 | [**SQL Automation & Audit Security**](02-sql-automation/) | Generated RAG-context column, payload procedure, audit triggers, immutable audit log, PII-masked view | **11 / 11** programmability checks |
| 3 | [**Galera Cluster & ColumnStore**](03-galera-columnstore/) | 3-node Galera on EC2 + EBS, manual `grastate.dat` bootstrap, ColumnStore on node 3 | Writes continued through a node failure; node rejoined and resynced |
| 4 | [**Vector Search**](04-vector-search/) | Sentence-aware token chunking, E5 embeddings, HNSW grid search, MariaDB Vector → ChromaDB | Recall@5 **1.0** at **~2 ms**; Hit@5 **1.00**, MRR **0.893** |
| 5 | [**Hybrid RAG Engine**](05-hybrid-rag/) | Entity- and keyword-routed retrieval over 3 stores, Ollama/Phi generation, citation validation | Retrieval **≈ 0.05 s** across all stores |
| 6 | [**Automation & Evaluation**](06-automation/) | Hash-based incremental sync for rows and PDFs, HTTP services, 20-question benchmark, citation audit | 1-row change detected among 9,296; index 64 → 66 → 64 on PDF add/delete |

Every milestone folder has a README with a summary, a map of its files, how to run it, and the detailed design and results.

## Repository map

```
├── 01-data-ingestion/       M1  sql/ · validation/ · tools/ · results/ · legacy_v1/
├── 02-sql-automation/       M2  sql/ · validation/
├── 03-galera-columnstore/   M3  cluster design, bootstrap protocol, failover test
├── 04-vector-search/        M4  chunking/ · scripts/ · notebooks/ · results/
├── 05-hybrid-rag/           M5  gigavolt/ (config, retrieval/, rag/, cli)
├── 06-automation/           M6  ingestion/ · services/ · benchmark/ · results/ · evidence/ · deploy/
├── docs/                    architecture diagram, deployment guide
├── scripts/                 deploy_database.sh (M1 + M2 schema, data and validation)
└── tests/                   52 offline unit tests + MariaDB integration tests
```

The Python code installs as one package, `gigavolt`, whose modules live in the milestone that introduced them: `gigavolt.chunking` (M4), `gigavolt.retrieval` and `gigavolt.rag` (M5), `gigavolt.ingestion` and `gigavolt.services` (M6).

## Quick start

```bash
pip install -e ".[dev]"        # add ,ml on the vector/document server
ruff check . && pytest -q      # offline: no databases or model servers needed
```

```bash
# Build the database from the raw ERP CSVs and run all 46 checks (MariaDB 10.11+)
scripts/deploy_database.sh --raw-dir data/raw/erp --validate
```

```bash
cp .env.example .env                    # endpoints and credentials
gigavolt-ingest-relational              # incremental relational sync
gigavolt-ingest-documents --apply       # incremental document sync
gigavolt-ask "Which lithium cell components are below their reorder level?"
```

Full two-server setup: [docs/deployment.md](docs/deployment.md). Source datasets are not redistributed; place them under `data/` (gitignored).

## Engineering highlights

- **Reconciled against production.** The cleansing pipeline was rebuilt from raw CSVs and compared cell by cell with the production load. That surfaced four production defects (carriage returns from a CRLF load, an uncleaned column, lost zip leading zeros, tag-wrapped `N/A`), which are now fixed and checked automatically. → [M1](01-data-ingestion/#reconciliation-against-the-production-load)
- **Honest provenance metrics.** A re-audit found the citation metric counted an appended fallback source list as model citations. The checker now scores claim-level citations separately. → [M5](05-hybrid-rag/#provenance-and-the-citation-audit)
- **Degrade, don't fail.** Every retrieval route isolates its own errors, and every client retries with reconnect, so a dead store shrinks the evidence instead of breaking the assistant. → [M5](05-hybrid-rag/)
- **Commit state last.** Both incremental pipelines save their checkpoint only after the downstream write succeeds. Documents are upserted first and obsolete chunks deleted second. → [M6](06-automation/)
- **Measure the right thing.** Vector latency excludes embedding time, and RAG latency is split by stage: generation is 99.5% of it, retrieval about 0.05 s. → [M6](06-automation/#rag-benchmark)

## Limitations and next steps

| Area | Today | Next |
|---|---|---|
| Latency | ~14 s median, almost all CPU inference of a local model | GPU or hosted inference with streaming |
| Citations | 3 / 20 answers had fully clean inline citations | Structured JSON output with per-claim source IDs; reject or retry invalid answers |
| Orchestration | Independent, idempotent ingestion jobs | One scheduled DAG (Airflow / Dagster) |
| Scale | 64 chunks, 200 telemetry documents | Re-run the tuning and benchmark scripts as the corpus grows |

## Background

Built over a semester as a six-milestone data-engineering project on AWS. Source datasets were supplied with the course and are not included here.
