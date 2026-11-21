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
[![License: MIT](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

</div>

Gigavolt turns messy ERP extracts, technical PDFs and battery telemetry into a question-answering system for field engineers. Each data type lands in the store built for it: **MariaDB** for relational ERP data, **ChromaDB** for semantic document search, **MongoDB** for telemetry. Incremental pipelines keep all three current, and a local LLM answers questions with citations that are checked against the evidence it retrieved.

## The problem

Gigavolt Dynamics, a fictional manufacturer of commercial battery energy-storage systems, keeps its knowledge in three disconnected places:

- **ERP records:** customers, installed equipment, service dispatches, parts and warranty claims, exported as CSVs full of mixed date formats, HTML fragments, duplicates and broken references;
- **technical documents:** manuals, SOPs, datasheets, engineering change orders and incident reports as PDFs;
- **battery telemetry:** voltage, temperature, state of charge and fault codes as nested JSON.

A field engineer troubleshooting a unit needs all three at once:

> *"Show the service history for EQ-5508 and what the manual says about over-temperature alarms."*
> → equipment, dispatch and warranty records (MariaDB) + recent readings and faults (MongoDB) + manual passages (ChromaDB) → cited answer → citation check

<p align="center"><img src="docs/architecture.svg" alt="Gigavolt architecture" width="100%"></p>

## Build roadmap

The system was built in six milestones on AWS. Each `mN-…` folder is self-contained: its README opens with a summary box, a map of the files and the commands to run that phase, followed by the design and measured results.

| # | Milestone | What was built | Headline result |
|:-:|---|---|---|
| 1 | [**Data Ingestion, Cleansing & Lakehouse Foundation**](m1-erp-pipeline/) | Bronze → staging → quarantine → 3NF Silver in SQL, unit-tested cleansing functions, raw-data profiler, production reconciliation | 9,498 raw → 9,296 clean rows, **0 orphaned FKs**; rebuild matches production on **99.993%** of cells |
| 2 | [**SQL Programming, RAG Payloads & Audit Security**](m2-database-logic/) | Generated RAG-context column, payload procedure, audit triggers, immutable audit log, PII-masked view | **11 / 11** programmability checks |
| 3 | [**High-Availability Galera Cluster & ColumnStore Analytics**](m3-ha-cluster/) | 3-node Galera on EC2 + EBS, manual bootstrap with automated safe-node selection, ColumnStore on node 3 | Writes continued through a node failure; ColumnStore **0.22 s** vs InnoDB 0.62 s; outage recovery rehearsed **25 / 25** |
| 4 | [**Text Chunking, Embedding Generation & Vector Database**](m4-semantic-search/) | Sentence-aware token chunking, E5 embeddings, HNSW grid search, MariaDB Vector prototype → ChromaDB | Recall@5 **1.0** at **~2 ms**; Hit@5 **1.00**, MRR **0.893** |
| 5 | [**Multi-Model Integration & Hybrid RAG Engine**](m5-rag-assistant/) | Entity- and keyword-routed retrieval over 3 stores, Ollama/Phi generation, citation validation | Retrieval **≈ 0.05 s** across all stores |
| 6 | [**Incremental Pipelines, Recovery & Evaluation**](m6-ops-evaluation/) | Hash-based incremental sync for rows and PDFs, HTTP services, 20-question benchmark, citation audit | 1-row change detected among 9,296; index 64 → 66 → 64 on PDF add/delete |

## Key numbers

| | |
|---|---|
| ERP data | 5 source tables · 9,498 raw rows → **9,296** Silver rows · 207 duplicates/orphans resolved · **0** orphaned foreign keys |
| Database validation | **46 / 46** automated checks: 20 integrity, 11 programmability, 15 cleansing-function unit tests |
| Reconciliation | Rebuild from raw CSVs matches the production load on **83,828 of 83,834** cells; 4 production defects found and fixed |
| High availability | 3-node Galera, **4,941** dispatches replicated to every node; failover under live writes; full-outage recovery rehearsed (**25 / 25** checks) |
| Analytics | 494,100-row aggregation: ColumnStore **0.224 s** vs InnoDB 0.622 s (single profiled run) |
| Vector search | 25 PDFs → 54 pages → **64** chunks · 384-d E5 embeddings · Recall@5 **1.0** at **~2 ms** median |
| RAG | 20 / 20 benchmark questions answered · retrieval **≈ 0.05 s** · generation is **99.5%** of the ~14 s latency |
| Quality gates | **58** offline unit tests + MariaDB integration tests · ruff · shellcheck · CI on every push |

## Tech stack

| Layer | Technologies |
|---|---|
| Infrastructure | AWS EC2 (Ubuntu), EBS volumes, security groups, systemd |
| Relational | MariaDB · Galera 4 (synchronous replication) · ColumnStore · stored procedures, triggers, generated columns · MariaDB Vector (prototype) |
| Document / telemetry | MongoDB |
| Vector search | ChromaDB · HNSW · Sentence-Transformers (`intfloat/e5-small-v2`) · PyMuPDF · Hugging Face tokenizers |
| LLM | Ollama · Phi (local, CPU) |
| Code | Python 3.10+ · PyMySQL · PyMongo · SQL · Bash |
| Quality | pytest · ruff · shellcheck · GitHub Actions |

## Repository map

```
├── m1-erp-pipeline/      M1  sql/ · validation/ · tools/ · results/ · legacy_v1/
├── m2-database-logic/    M2  sql/ · validation/
├── m3-ha-cluster/        M3  config/ · sql/ · scripts/ · local-test/ · results/ · recovery runbook
├── m4-semantic-search/   M4  chunking/ · scripts/ · notebooks/ · results/
├── m5-rag-assistant/     M5  gigavolt/ (config, retrieval/, rag/, cli)
├── m6-ops-evaluation/    M6  ingestion/ · services/ · benchmark/ · results/ · evidence/ · deploy/
├── docs/                     architecture diagram, deployment guide
├── scripts/                  deploy_database.sh (M1 + M2 schema, data and validation)
└── tests/                    58 offline unit tests + MariaDB integration tests
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

Full two-server setup: [docs/deployment.md](docs/deployment.md). The source datasets are not redistributed; place them under `data/` (gitignored).

## Engineering highlights

- **Reconciled against production.** The cleansing pipeline was rebuilt from raw CSVs and compared cell by cell with the production load. That surfaced four production defects (carriage returns from a CRLF load, an uncleaned column, lost zip leading zeros, tag-wrapped `N/A`), which are now fixed and checked automatically. → [M1](m1-erp-pipeline/#reconciliation-against-the-production-load)
- **Recovery that refuses to guess.** After a full cluster outage, the bootstrap selector refuses to choose while any node's position is unknown, then picks the most advanced node. A local 3-node rehearsal shows it avoiding a stale node that would have silently dropped committed writes. → [M3](m3-ha-cluster/#local-rehearsal)
- **Honest provenance metrics.** A re-audit found that the citation metric counted an appended fallback source list as model citations. The checker now scores claim-level citations separately. → [M5](m5-rag-assistant/#provenance-and-the-citation-audit)
- **Degrade, don't fail.** Every retrieval route isolates its own errors, and every client retries with reconnect, so a dead store shrinks the evidence instead of breaking the assistant. → [M5](m5-rag-assistant/)
- **Commit state last.** Both incremental pipelines save their checkpoint only after the downstream write succeeds. Documents are upserted first, and obsolete chunks are deleted second. → [M6](m6-ops-evaluation/)
- **Measure the right thing.** Vector latency excludes embedding time, and RAG latency is split by stage: generation is 99.5% of it, retrieval about 0.05 s. → [M6](m6-ops-evaluation/#rag-benchmark)

## Limitations and next steps

| Area | Today | Next |
|---|---|---|
| Latency | ~14 s median, almost all CPU inference of a local model | GPU or hosted inference with streaming |
| Citations | 3 / 20 answers had fully clean inline citations | Structured JSON output with per-claim source IDs; reject or retry invalid answers |
| Orchestration | Independent, idempotent ingestion jobs | One scheduled DAG (Airflow / Dagster) |
| Scale | 64 chunks, 200 telemetry documents | Re-run the tuning and benchmark scripts as the corpus grows |

## Background

Built by **Meet Kothari** over a semester as a six-milestone data-engineering project on AWS. Gigavolt Dynamics is a fictional company; the source datasets were supplied with the course and are not included here.

## License

[MIT](LICENSE)
