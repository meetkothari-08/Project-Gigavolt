# Vector search: chunking, embeddings and HNSW tuning

The scripts in [`vector_search/`](../vector_search/) build the document corpus in order. The chunker itself lives in [`src/gigavolt/ingestion/documents/chunking.py`](../src/gigavolt/ingestion/documents/chunking.py) and is shared with the incremental pipeline, so batch builds and incremental updates always produce identical chunk IDs.

| Step | Script | Output |
|---|---|---|
| 1 | `extract_and_chunk.py` | `extracted_pages.jsonl`, `chunks.jsonl`, `summary.json` |
| 2 | `validate_chunks.py` | PASS/FAIL report (IDs, budget, ranges, overlap) |
| 3 | `embed_to_mariadb.py` | MariaDB `VECTOR(384)` table with an HNSW index (prototype) |
| 4 | `export_mariadb_vectors.py` | `mariadb_vectors_export.jsonl` |
| 5 | `build_chroma_collection.py` | Final ChromaDB collection `gigavolt_m4_final` |
| | `tune_hnsw.py`, `benchmark_chroma_search.py`, `benchmark_mariadb_recall.py` | Tuning and latency/recall CSVs |
| | `evaluate_relevance.py`, `review_relevance.py` | Source-level Hit@5 / MRR, optional human review |

The analysis notebook is [`vector_search/notebooks/vector_search_benchmark.ipynb`](../vector_search/notebooks/vector_search_benchmark.ipynb).

## Chunking

* Each PDF is processed as **one continuous document**, with pages joined by a blank line. Chunks can therefore cross page boundaries, and every chunk keeps `page_start` and `page_end`.
* Chunks are sized in the **embedding model's own tokens** (`intfloat/e5-small-v2` tokenizer), with a hard cap of **300 tokens** and about **50 tokens of overlap**.
* Boundaries snap to the last sentence or line break within a 30-token backtrack window, so chunks rarely end mid-sentence.
* Every candidate span is re-tokenized on its own and shrunk if needed, because tokenization at a substring edge can differ from the full-document tokenization.
* IDs are deterministic: `sha256(relative_path)[:16]` + `-c0001`.

| Corpus | Value |
|---|---|
| PDFs / pages / pages with text | 25 / 54 / 53 (one architecture page is an image) |
| Chunks | 64 |
| Tokens per chunk | min 63, max 300, mean 249.9 |
| Overlap between adjacent chunks | 39 of 39 pairs ≥ 50 tokens (min 50, max 63, mean 54.4) |

## Embeddings

`intfloat/e5-small-v2` produces 384-dimensional embeddings. It is small enough for CPU-only EC2 instances and is trained for asymmetric retrieval. Documents are encoded with a `passage: ` prefix and queries with `query: `, as the model expects. All vectors are L2-normalized, so cosine similarity equals the dot product. Query embedding is served by a small HTTP service ([`services/embedding_api.py`](../src/gigavolt/services/embedding_api.py)), so the RAG server never loads the model.

## Vector store choice

A native **MariaDB Vector** prototype came first, because it kept vectors next to the relational data. Measured with `mhnsw_ef_search` set to 10, 20 and 40, it gave Recall@5 of 0.95, 0.975 and 1.00, at about 0.63 ms median. The final store is **ChromaDB**, which provides a persistent collection with metadata filtering (`where={"source_id": …}`) and an HTTP server. That filtering is what makes per-document replace and delete in the incremental pipeline straightforward.

## HNSW tuning

Nine temporary collections covered `M ∈ {8, 16, 32}` × `ef_construction ∈ {50, 100, 200}` at `ef_search = 20`. Each was scored against exact cosine search over the same saved vectors ([results](../benchmarks/results/vector/chroma_hnsw_tuning.csv)).

* Every configuration reached **Recall@5 = 1.0**, with P50 between 1.12 and 1.17 ms and P99 at most 1.23 ms.
* The smallest graph (**M = 8, ef_construction = 50**) was as accurate and as fast as the largest, so it was chosen: it has the lowest memory and build cost.
* On the final collection, `ef_search ∈ {10, 20, 40, 80}` all held Recall@5 = 1.0, at about 2.0 ms median per query over 20 timed runs after warm-up ([results](../benchmarks/results/vector/chroma_final_benchmark.csv)). That is an order of magnitude under the 20 ms target. **`ef_search = 20`** was kept as headroom for corpus growth.

With 64 vectors, HNSW is nearly exhaustive, so these numbers show correctness and overhead rather than scaling behaviour. The tuning script is the tool to re-run when the corpus grows.

## Retrieval quality

Each of 25 natural-language questions was labelled with the document expected to answer it ([results](../benchmarks/results/vector/relevance_summary.csv)).

| Metric | Value |
|---|---|
| Expected-source Hit@5 | **1.00** (25 / 25) |
| Expected-source MRR | **0.893** |

These are source-level proxy metrics. A human relevance review tool exists (`review_relevance.py`), but only 6 of the 125 candidates were hand-labelled, so no human-judged precision is claimed.
