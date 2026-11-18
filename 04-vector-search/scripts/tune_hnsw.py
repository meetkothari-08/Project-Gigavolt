#!/usr/bin/env python3
"""HNSW construction tuning: build temporary ChromaDB collections for every
M in {8, 16, 32} x ef_construction in {50, 100, 200} (ef_search fixed at 20),
then measure Recall@5 against exact cosine search and P50/P95/P99 latency.

    python 04-vector-search/scripts/tune_hnsw.py
"""

import csv
import time

import chromadb
import numpy as np
from sentence_transformers import SentenceTransformer

from _common import BENCHMARK_QUERIES as QUERIES
from _common import CHROMA_DIR, MODEL_NAME, PROCESSED_DIR, read_jsonl
from _common import EXPORT_FILE as EXPORT

OUTPUT = PROCESSED_DIR / "chroma_hnsw_tuning.csv"

TOP_K = 5
RUNS = 10
FIXED_EF_SEARCH = 20

M_VALUES = [8, 16, 32]
EF_CONSTRUCTION_VALUES = [50, 100, 200]


def load_export():
    records = read_jsonl(EXPORT)

    ids = [r["chunk_id"] for r in records]
    vectors = np.asarray(
        [r["embedding"] for r in records],
        dtype=np.float32,
    )

    if len(records) != 64 or len(set(ids)) != len(ids):
        raise RuntimeError("Expected 64 records with unique IDs.")

    if vectors.shape != (64, 384):
        raise RuntimeError(f"Unexpected vector shape: {vectors.shape}")

    return records, ids, vectors


def main():
    records, ids, exact_vectors = load_export()
    exact_vectors /= np.maximum(
        np.linalg.norm(exact_vectors, axis=1, keepdims=True),
        1e-12,
    )

    print("Loading query embedding model...")
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    query_vectors = model.encode(
        ["query: " + q for q in QUERIES],
        normalize_embeddings=True,
        convert_to_numpy=True,
        batch_size=1,
        show_progress_bar=False,
    ).astype(np.float32)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    results = []

    for m in M_VALUES:
        for efc in EF_CONSTRUCTION_VALUES:
            name = f"m4tune_m{m}_efc{efc}"

            # Remove only this temporary test collection if a previous
            # interrupted run left it behind.
            if name in client.list_collections():
                client.delete_collection(name)

            print(f"\nTesting M={m}, ef_construction={efc}")

            collection = client.create_collection(
                name=name,
                embedding_function=None,
                metadata={
                    "purpose": "temporary HNSW parameter comparison",
                    "max_neighbors": m,
                    "ef_construction": efc,
                },
                configuration={
                    "hnsw": {
                        "space": "cosine",
                        "max_neighbors": m,
                        "ef_construction": efc,
                        "ef_search": FIXED_EF_SEARCH,
                        "batch_size": 10,
                        "sync_threshold": 100,
                        "num_threads": 1,
                    }
                },
            )

            # Reuse the saved embeddings. Do not call the document
            # embedding model again.
            for start in range(0, len(records), 10):
                batch = records[start:start + 10]
                batch_ids = [r["chunk_id"] for r in batch]

                collection.add(
                    ids=batch_ids,
                    embeddings=[r["embedding"] for r in batch],
                    documents=[r["chunk_text"] for r in batch],
                    metadatas=[
                        {
                            "source_filename": r["source_filename"],
                            "source_path": r["source_path"],
                            "source_id": r["source_id"],
                            "page_number": int(r["page_number"]),
                            "token_count": int(r["token_count"]),
                            "created_at": str(r["created_at"]),
                        }
                        for r in batch
                    ],
                )

            if collection.count() != 64:
                raise RuntimeError(f"{name}: record count mismatch.")

            # Confirm HNSW settings actually applied.
            config = collection.configuration["hnsw"]
            print(
                "Actual settings:",
                {
                    key: config.get(key)
                    for key in (
                        "space", "max_neighbors",
                        "ef_construction", "ef_search", "batch_size"
                    )
                },
            )

            query_recalls = []
            timings = []

            for query, qvec in zip(QUERIES, query_vectors):
                # Exact top-5 provides the nearest-neighbor ground truth.
                exact_indices = np.argsort(
                    1.0 - exact_vectors @ qvec
                )[:TOP_K]
                exact_top_ids = {ids[i] for i in exact_indices}

                def search():
                    return collection.query(
                        query_embeddings=[qvec.tolist()],
                        n_results=TOP_K,
                        include=["distances"],
                    )

                for _ in range(3):
                    search()

                run_times = []
                result = None

                for _ in range(RUNS):
                    start = time.perf_counter()
                    result = search()
                    run_times.append(
                        (time.perf_counter() - start) * 1000
                    )

                found_ids = set(result["ids"][0])
                recall = len(exact_top_ids & found_ids) / TOP_K

                query_recalls.append(recall)
                timings.extend(run_times)

            p50, p95, p99 = np.percentile(
                timings, [50, 95, 99]
            )

            row = {
                "M": m,
                "ef_construction": efc,
                "ef_search": FIXED_EF_SEARCH,
                "mean_recall_at_5": float(np.mean(query_recalls)),
                "p50_ms": float(p50),
                "p95_ms": float(p95),
                "p99_ms": float(p99),
                "max_ms": float(max(timings)),
                "records": collection.count(),
            }
            results.append(row)

            print(
                f"Recall@5={row['mean_recall_at_5']:.3f} | "
                f"P50={row['p50_ms']:.3f} ms | "
                f"P95={row['p95_ms']:.3f} ms"
            )

            # Delete only the temporary benchmark collection.
            client.delete_collection(name)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    print("\n" + "=" * 60)
    print("HNSW CONSTRUCTION TUNING COMPLETE")
    print("=" * 60)
    for row in sorted(results, key=lambda r: (r["p50_ms"], -r["mean_recall_at_5"])):
        print(
            f"M={row['M']:2}, ef_construction={row['ef_construction']:3} | "
            f"Recall@5={row['mean_recall_at_5']:.3f} | "
            f"P50={row['p50_ms']:.3f} ms | "
            f"P95={row['p95_ms']:.3f} ms"
        )

    print(f"\nCSV saved to: {OUTPUT}")


if __name__ == "__main__":
    main()
