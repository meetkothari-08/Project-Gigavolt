#!/usr/bin/env python3
"""Benchmark the MariaDB Vector prototype: Recall@5 against exact cosine search
and median query latency for mhnsw_ef_search in {10, 20, 40}.

    python m4-semantic-search/scripts/benchmark_mariadb_recall.py
"""

import csv
import json
import time

import numpy as np
import pymysql
from sentence_transformers import SentenceTransformer

from _common import MODEL_NAME, PROCESSED_DIR, vector_db_config

TOP_K = 5
RUNS = 20
EF_SEARCH_VALUES = [10, 20, 40]

OUTPUT_FILE = PROCESSED_DIR / "mariadb_recall_benchmark.csv"


QUERIES = [
    "What caused the X-7000 contactor flashover?",
    "What corrective action prevents pre-charge contactor failure?",
    "What are the emergency procedures for thermal runaway?",
    "How should technicians perform firmware flashing?",
    "What are the procedures for X-7000 site acceptance testing?",
    "What causes low isolation trips in battery equipment?",
    "What are the battery cell temperature and voltage specifications?",
    "What corrective actions address chiller relief valve problems?",
]


def encode_vector(vector):
    return json.dumps(
        [float(value) for value in vector],
        separators=(",", ":"),
    )


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("Loading E5 model...")
    model = SentenceTransformer(MODEL_NAME, device="cpu")

    print("Encoding benchmark queries...")
    query_vectors = model.encode(
        ["query: " + query for query in QUERIES],
        batch_size=1,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )

    print("Connecting to MariaDB...")
    conn = pymysql.connect(**vector_db_config())

    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT chunk_id, VEC_ToText(embedding)
                FROM document_chunks
            """)
            stored_rows = cursor.fetchall()

            if len(stored_rows) < TOP_K:
                raise RuntimeError(
                    "Not enough document vectors for Recall@5."
                )

            ids = []
            vectors = []

            for chunk_id, vector_text in stored_rows:
                if isinstance(vector_text, bytes):
                    vector_text = vector_text.decode("utf-8")

                ids.append(chunk_id)
                vectors.append(json.loads(vector_text))

            matrix = np.asarray(vectors, dtype=np.float32)

            if matrix.shape[1] != 384:
                raise RuntimeError(
                    f"Unexpected stored vector shape: {matrix.shape}"
                )

            # Document vectors and query vectors are normalized.
            # Exact top-K is therefore calculated by cosine distance.
            matrix = matrix / np.maximum(
                np.linalg.norm(matrix, axis=1, keepdims=True),
                1e-12,
            )

            results = []

            sql = """
                SELECT chunk_id
                FROM document_chunks
                ORDER BY VEC_DISTANCE_COSINE(
                    embedding, VEC_FromText(%s)
                ) ASC
                LIMIT 5
            """

            for ef in EF_SEARCH_VALUES:
                cursor.execute(
                    f"SET SESSION mhnsw_ef_search = {int(ef)}"
                )

                query_recalls = []
                query_medians = []

                for query, qvec in zip(QUERIES, query_vectors):
                    qvec = qvec / max(
                        float(np.linalg.norm(qvec)),
                        1e-12,
                    )

                    # Exact ground truth from all stored embeddings.
                    distances = 1.0 - matrix @ qvec
                    exact_indices = np.argsort(distances)[:TOP_K]
                    exact_ids = {ids[i] for i in exact_indices}

                    vector_text = encode_vector(qvec)

                    # Warm up the database before timing.
                    for _ in range(3):
                        cursor.execute(sql, (vector_text,))
                        cursor.fetchall()

                    timings = []
                    approximate_ids = set()

                    for _ in range(RUNS):
                        start = time.perf_counter()
                        cursor.execute(sql, (vector_text,))
                        rows = cursor.fetchall()
                        timings.append(
                            (time.perf_counter() - start) * 1000
                        )
                        approximate_ids = {
                            row[0] for row in rows
                        }

                    recall = (
                        len(exact_ids & approximate_ids) / TOP_K
                    )

                    median_ms = float(np.median(timings))
                    query_recalls.append(recall)
                    query_medians.append(median_ms)

                    results.append({
                        "ef_search": ef,
                        "query": query,
                        "recall_at_5": recall,
                        "median_latency_ms": median_ms,
                        "exact_top5": "|".join(
                            ids[i] for i in exact_indices
                        ),
                        "approximate_top5": "|".join(
                            sorted(approximate_ids)
                        ),
                    })

                print(f"\nef_search = {ef}")
                print(
                    f"Mean Recall@5: "
                    f"{np.mean(query_recalls):.3f}"
                )
                print(
                    f"Median query latency: "
                    f"{np.median(query_medians):.3f} ms"
                )

            with OUTPUT_FILE.open(
                "w", newline="", encoding="utf-8"
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=list(results[0].keys()),
                )
                writer.writeheader()
                writer.writerows(results)

            print("\nBenchmark complete.")
            print(f"CSV saved to: {OUTPUT_FILE}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
