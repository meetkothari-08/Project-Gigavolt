# Milestone 6 · Automated Pipeline, Optimization & System Synthesis

Keeps every store current as data changes, recovers from service failures, and measures the whole system. Hash-based incremental ingestion syncs the relational and document stores. HTTP services run the embedding model and an ingestion trigger, and a 20-question benchmark profiles latency per stage and audits citations.

| | |
|---|---|
| **Relational sync** | 9,296 records baselined with 0 invalid; a single-row change (EQ-5508) detected and processed |
| **Document sync** | Add → 2 chunks indexed (64 → 66 vectors); delete → vectors removed (66 → 64) |
| **Recovery** | Embedding service stopped and restarted; health check and remote retrieval recovered with no RAG restart |
| **Benchmark** | 20/20 answered · P50 13.6–15.1 s across 5 runs · generation = **99.5%** of latency |

## What's here

| Path | Contents |
|---|---|
| [`ingestion/relational/`](ingestion/relational/) | Row-hash change detection, validation, SQLite state, audit-log checkpoint |
| [`ingestion/documents/pipeline.py`](ingestion/documents/pipeline.py) | Incremental PDF → chunk → embed → ChromaDB sync, with deletions |
| [`services/`](services/) | Embedding API (`:8001`) and authenticated ingestion trigger (`:8002`) |
| [`benchmark/rag_benchmark.py`](benchmark/rag_benchmark.py) | 20-question benchmark with per-stage P50/P95/P99 |
| [`benchmark/audit_saved_answers.py`](benchmark/audit_saved_answers.py) | Offline claim-level citation re-audit |
| [`results/`](results/) | Five saved benchmark runs and the citation audit |
| [`evidence/`](evidence/) | Log excerpts from the incremental-ingestion tests on EC2 |
| [`deploy/systemd/`](deploy/systemd/) | Service units for the vector/document server |

## Run it

```bash
gigavolt-ingest-relational --dry-run     # detect + validate, no state written
gigavolt-ingest-relational               # incremental relational sync
gigavolt-ingest-documents --apply        # incremental document sync (vector server)
python 06-automation/benchmark/rag_benchmark.py
```

## Incremental relational ingestion

[`ingestion/relational/`](ingestion/relational/) keeps downstream consumers in step with the Silver tables without reprocessing everything:

1. **Detect.** Stream every row of the six tables (500-row batches) and compute a SHA-256 over its canonical JSON form (sorted keys, ISO dates, Decimal as string). Compare with the hash saved in SQLite to classify each row as `NEW`, `MODIFIED` or unchanged.
2. **Validate.** Check required fields, numeric and date parsing, and domain rules (non-negative stock, approved ≤ claimed).
3. **Record.** Save a row's hash only after it validates, so an invalid or failed row is retried on the next run.
4. **Audit checkpoint.** Read `Audit_Logs` rows after the last processed `audit_id`, and advance the checkpoint only after every event is handled.

`--dry-run` detects and validates without writing state.

**Evidence** ([log excerpt](evidence/relational_pipeline_change_detection.log)):

* First full run: 9,296 new, 9,296 processed, **0 invalid**, 0 failed, and 6 audit events consumed.
* `EQ-5508` modified, then run: `modified: 1, processed: 1`. The value was restored and the pipeline run again: `modified: 1` again, because restoring the value changes the hash a second time.
* Re-verified locally against the rebuilt database: a first run baselines 9,296 rows, and the second reports 9,296 unchanged in about 0.3 s.

## Incremental document ingestion

[`ingestion/documents/pipeline.py`](ingestion/documents/pipeline.py) keeps ChromaDB in sync with the documents folder:

* **Unchanged** files (same SHA-256 as the last run) are skipped without being opened.
* **New or modified** files are extracted, chunked and embedded. New chunks are upserted *first*, and only then are chunk IDs that no longer exist deleted, so a reader never sees a document with zero chunks.
* **Deleted** files have their vectors removed by `source_id`, and then their state row.
* State is committed only after ChromaDB accepts the write.
* If the folder is empty, deletion reconciliation is skipped, because an empty folder is more likely a failed mount than an intentional purge.

The pipeline runs from the CLI or behind an authenticated HTTP trigger ([`services/ingestion_api.py`](services/ingestion_api.py)). The trigger uses a constant-time API-key comparison and refuses concurrent runs with HTTP 409.

**Evidence** ([log excerpt](evidence/document_pipeline_add_delete_test.log)):

| Run | Discovered | Action | Collection size |
|---|---:|---|---:|
| Baseline | 25 | 25 unchanged | 64 |
| Test PDF added | 26 | 1 new → 2 chunks indexed | **66** |
| Test PDF deleted | 25 | 1 deleted → 2 vectors removed | **64** |

## Service recovery

The vector/document server runs ChromaDB (`:8000`), the embedding API (`:8001`) and the ingestion trigger (`:8002`) as services. Example units are in [`deploy/systemd/`](deploy/systemd/). The RAG server reaches them over the VPC. The recovery drill:

1. Confirm `GET /health` on the embedding API returns `healthy`.
2. Stop the service and confirm the health check fails.
3. Restart the service and confirm the health check recovers.
4. From the RAG server, confirm remote connectivity to the embedding API, then confirm vector retrieval works again.

By design, while the embedding service is down the RAG pipeline records the failure in the response's `errors` list and still answers from MariaDB and MongoDB. Each retriever retries with reconnect, so no RAG restart is needed once the service is back.

## RAG benchmark

[`benchmark/rag_benchmark.py`](benchmark/rag_benchmark.py) runs 20 questions covering document lookup, safety procedures, supplier and inventory questions, model telemetry and multi-source synthesis. It records per-question latency, source counts, citations and errors. Five runs between 2026-11-13 and 2026-11-15 ([results](results/)):

| Run | Success | Mean | P50 | P95 | P99 | Throughput |
|---|---:|---:|---:|---:|---:|---:|
| 11-13 05:00 | 20/20 | 14.19 s | 14.68 s | 18.21 s | 19.06 s | 0.070 req/s |
| 11-14 21:38 | 20/20 | 14.25 s | 14.77 s | 18.79 s | 19.62 s | 0.070 req/s |
| 11-14 21:55 | 20/20 | 15.15 s | 15.00 s | 19.92 s | 20.41 s | 0.066 req/s |
| 11-14 22:21 | 20/20 | 14.90 s | 15.09 s | 19.63 s | 19.79 s | 0.067 req/s |
| 11-15 07:52 | 20/20 | 13.44 s | 13.64 s | 17.81 s | 17.96 s | 0.074 req/s |

**Where the time goes.** In every run, LLM generation accounts for **99.5–99.7 %** of end-to-end latency. Retrieval across all three stores takes about **0.05 s** (median) per question. The 5-second target is therefore a model-serving problem, not a data problem: on CPU-only instances, Phi generation alone takes 13–15 s. The benchmark script now records retrieval and generation timing separately and reports P50/P95/P99 for each stage.

## Known limitations

* **No single orchestration entry point.** The relational and document pipelines are separate, idempotent jobs, run on schedule or on demand on their respective servers. They are not one DAG.
* **Claim-level citations are weak.** See [Milestone 5](../05-hybrid-rag/#provenance-and-the-citation-audit).
* **The corpus is small** (64 chunks, 200 telemetry documents), so vector-index tuning shows correctness rather than scale.
* **The telemetry and ERP serial-number schemes differ** in the source data (`SN-X7-0094` vs `SN-X5000-42935`), so the unit-level MariaDB → MongoDB hop only links when a question names the telemetry serial directly.

## Next steps

1. **Latency.** Serve the model on a GPU, or use a hosted model, for generation, and stream tokens. Retrieval is already sub-100 ms.
2. **Citations.** Ask for structured output (JSON with `claims[].source_ids`) instead of free-text brackets, and reject or retry answers whose `model_citations_all_valid` is false.
3. **Orchestration.** Wrap the two pipelines and the benchmark in a scheduler DAG (for example Airflow or Dagster), with the existing state databases as idempotency keys.
4. **Entity resolution.** Add a mapping table between ERP equipment IDs and telemetry serial numbers.
