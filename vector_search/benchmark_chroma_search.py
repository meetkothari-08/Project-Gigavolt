#!/usr/bin/env python3
"""Final ChromaDB benchmark: for ef_search in {10, 20, 40, 80}, measure Recall@5
against exact cosine nearest neighbours and median search latency
(20 timed runs per query after 3 warm-up runs). Query-embedding time is
excluded, so this measures database search only.

    python vector_search/benchmark_chroma_search.py
"""

import csv
import sys
import time

import chromadb
import numpy as np
from sentence_transformers import SentenceTransformer

from _common import BENCHMARK_QUERIES as QUERIES
from _common import CHROMA_DIR, EXPORT_FILE, MODEL_NAME, PROCESSED_DIR, read_jsonl
from _common import FINAL_COLLECTION as COLLECTION_NAME

OUTPUT_FILE = PROCESSED_DIR / "chroma_final_benchmark.csv"

TOP_K = 5
RUNS = 20
EF_SEARCH_VALUES = [10, 20, 40, 80]


def read_export():
    records = read_jsonl(EXPORT_FILE)

    if not records:
        raise RuntimeError("Vector export is empty.")

    ids = [r["chunk_id"] for r in records]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate IDs in vector export.")

    vectors = np.asarray(
        [r["embedding"] for r in records],
        dtype=np.float32,
    )

    if vectors.shape != (len(records), 384):
        raise RuntimeError(
            f"Unexpected export embedding shape: {vectors.shape}"
        )

    return records, ids, vectors


def main():
    if not EXPORT_FILE.exists():
        raise FileNotFoundError(
            f"Missing export file: {EXPORT_FILE}"
        )

    records, ids, exact_vectors = read_export()

    print("=" * 65)
    print("GIGAVOLT M4: CHROMADB SEARCH BENCHMARK")
    print("=" * 65)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_collection(COLLECTION_NAME)

    if collection.count() != len(records):
        raise RuntimeError(
            f"ChromaDB contains {collection.count()} records, "
            f"but the export contains {len(records)}."
        )

    # Ensure every exported record ID exists in the collection.
    stored_ids = set(collection.get()["ids"])
    if stored_ids != set(ids):
        raise RuntimeError("Collection IDs don't match the export.")

    print(f"ChromaDB collection: {COLLECTION_NAME}")
    print(f"Verified records: {collection.count()}")
    print(f"Model: {MODEL_NAME}")

    print("\nLoading query embedding model...")
    model = SentenceTransformer(MODEL_NAME, device="cpu")

    query_vectors = model.encode(
        ["query: " + q for q in QUERIES],
        batch_size=1,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype(np.float32)

    # Normalize the exported vectors for exact cosine ground truth.
    exact_vectors /= np.maximum(
        np.linalg.norm(exact_vectors, axis=1, keepdims=True),
        1e-12,
    )

    rows = []

    for ef_search in EF_SEARCH_VALUES:
        # ef_search is mutable in ChromaDB's HNSW configuration.
        collection.modify(
            configuration={
                "hnsw": {"ef_search": ef_search}
            }
        )

        config = collection.configuration
        print(f"\n--- ef_search = {ef_search} ---")
        print(f"Current HNSW configuration: {config}")

        recalls = []
        all_latencies = []

        for query, query_vector in zip(QUERIES, query_vectors):
            # Exact top-K over all saved vectors forms the benchmark
            # ground truth; this does not depend on ChromaDB's index.
            exact_distances = 1.0 - exact_vectors @ query_vector
            exact_indices = np.argsort(exact_distances)[:TOP_K]
            exact_top_ids = {ids[i] for i in exact_indices}

            qvec = query_vector.tolist()

            def search():
                return collection.query(
                    query_embeddings=[qvec],
                    n_results=TOP_K,
                    include=["documents", "metadatas", "distances"],
                )

            # Warm up the query path before taking measurements.
            for _ in range(3):
                search()

            timings = []
            result = None

            for _ in range(RUNS):
                start = time.perf_counter()
                result = search()
                timings.append(
                    (time.perf_counter() - start) * 1000
                )

            all_latencies.extend(timings)

            found_ids = set(result["ids"][0])
            recall = len(exact_top_ids & found_ids) / TOP_K
            recalls.append(recall)

            rows.append({
                "ef_search": ef_search,
                "query": query,
                "recall_at_5": recall,
                "median_latency_ms": float(np.median(timings)),
                "exact_top5": "|".join(
                    ids[i] for i in exact_indices
                ),
                "chromadb_top5": "|".join(result["ids"][0]),
            })

            # Print retrieved evidence once per query at ef_search=40.
            if ef_search == 40:
                print(f"\nQuery: {query}")
                for rank, (chunk_id, document, metadata, distance) in enumerate(
                    zip(
                        result["ids"][0],
                        result["documents"][0],
                        result["metadatas"][0],
                        result["distances"][0],
                    ),
                    start=1,
                ):
                    print(
                        f"{rank}. {metadata.get('source_filename')} "
                        f"(pages {metadata.get('page_start')}-"
                        f"{metadata.get('page_end')}), "
                        f"distance={distance:.4f}"
                    )
                    print(f"   ID: {chunk_id}")
                    print(f"   {document[:180].replace(chr(10), ' ')}")

        p50, p95, p99 = np.percentile(
            all_latencies, [50, 95, 99]
        )

        mean_recall = float(np.mean(recalls))

        print(f"\nMean Recall@5: {mean_recall:.3f}")
        print(f"P50 search latency: {p50:.3f} ms")
        print(f"P95 search latency: {p95:.3f} ms")
        print(f"P99 search latency: {p99:.3f} ms")
        print(f"Minimum latency: {min(all_latencies):.3f} ms")
        print(f"Maximum latency: {max(all_latencies):.3f} ms")

        if ef_search == EF_SEARCH_VALUES[0]:
            print("\nBenchmark target: median below 20 ms")

        print(f"Median target met: {'YES' if p50 < 20 else 'NO'}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0].keys()),
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\n" + "=" * 65)
    print("CHROMADB BENCHMARK COMPLETE")
    print("=" * 65)
    print(f"Queries: {len(QUERIES)}")
    print(f"Runs per query and setting: {RUNS}")
    print(f"CSV: {OUTPUT_FILE}")
    print("Query embedding/model time is excluded from database latency.")
    print("Recall@5 is against exact cosine nearest neighbors.")
    print("HNSW settings and results are recorded for comparison.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
