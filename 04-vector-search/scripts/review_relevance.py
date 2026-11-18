#!/usr/bin/env python3
"""Interactive human relevance review of the candidates written by
evaluate_relevance.py. Labels are saved after every answer, so the review can
be resumed. Reports judged Precision@5, MRR@5 and NDCG@5.

    python 04-vector-search/scripts/review_relevance.py
"""

import csv
import math
from collections import defaultdict

from _common import PROCESSED_DIR

INPUT = PROCESSED_DIR / "relevance_candidates.csv"
OUTPUT = PROCESSED_DIR / "human_relevance_judgments.csv"

if not INPUT.exists():
    raise FileNotFoundError(f"Missing candidate file: {INPUT}")

with INPUT.open(encoding="utf-8-sig", newline="") as f:
    candidates = list(csv.DictReader(f))

if not candidates:
    raise RuntimeError("No candidate rows found.")

groups = defaultdict(list)
for row in candidates:
    groups[row["query_id"]].append(row)

for rows in groups.values():
    rows.sort(key=lambda r: int(r["rank"]))

fields = [
    "query_id", "query", "rank", "chunk_id",
    "source_filename", "page_start", "page_end",
    "cosine_distance", "human_relevant", "review_notes",
]

# Resume from existing judgments if the script is restarted.
saved = {}
if OUTPUT.exists():
    with OUTPUT.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            saved[(row["query_id"], row["chunk_id"])] = row

def save():
    ordered = []
    for query_id in groups:
        for candidate in groups[query_id]:
            key = (candidate["query_id"], candidate["chunk_id"])
            old = saved.get(key, {})
            ordered.append({
                "query_id": candidate["query_id"],
                "query": candidate["query"],
                "rank": candidate["rank"],
                "chunk_id": candidate["chunk_id"],
                "source_filename": candidate["source_filename"],
                "page_start": candidate["page_start"],
                "page_end": candidate["page_end"],
                "cosine_distance": candidate["cosine_distance"],
                "human_relevant": old.get("human_relevant", ""),
                "review_notes": old.get("review_notes", ""),
            })

    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ordered)

def compute_metrics():
    relevant_queries = []
    all_judged = []

    for query_id, rows in groups.items():
        judged = []
        for row in rows:
            old = saved.get((query_id, row["chunk_id"]), {})
            label = old.get("human_relevant", "").strip()
            if label in {"0", "1"}:
                judged.append((int(row["rank"]), int(label)))
                all_judged.append(int(label))

        if judged:
            judged.sort()
            relevant_ranks = [rank for rank, label in judged if label == 1]
            precision = sum(label for _, label in judged) / len(judged)
            reciprocal_rank = (
                1 / relevant_ranks[0] if relevant_ranks else 0.0
            )

            dcg = sum(
                label / math.log2(rank + 1)
                for rank, label in judged
            )
            ideal = sorted(
                [label for _, label in judged],
                reverse=True
            )
            idcg = sum(
                label / math.log2(i + 2)
                for i, label in enumerate(ideal)
            )
            ndcg = dcg / idcg if idcg else 0.0

            relevant_queries.append(
                (precision, reciprocal_rank, ndcg)
            )

    total = sum(len(rows) for rows in groups.values())
    judged_count = len(all_judged)

    print("\n" + "=" * 60)
    print("HUMAN RELEVANCE REVIEW PROGRESS")
    print("=" * 60)
    print(f"Judged results: {judged_count}/{total}")

    if all_judged:
        print(f"Judged chunks marked relevant: {sum(all_judged)}")
        print(f"Judged-chunk relevance rate: {sum(all_judged)/len(all_judged):.3f}")

    if relevant_queries:
        print(f"Mean judged Precision@5: {sum(x[0] for x in relevant_queries)/len(relevant_queries):.3f}")
        print(f"Mean judged MRR@5:       {sum(x[1] for x in relevant_queries)/len(relevant_queries):.3f}")
        print(f"Mean judged NDCG@5:      {sum(x[2] for x in relevant_queries)/len(relevant_queries):.3f}")

    print(f"Saved to: {OUTPUT}")

print("HUMAN RELEVANCE REVIEW")
print("Judge relevance to the query, not just filename similarity.")
print("y = relevant, n = not relevant, s = skip, q = save and quit.")
print("A chunk is relevant when its content meaningfully helps answer the query.")

for query_id, rows in groups.items():
    query_text = rows[0]["query"]
    expected = rows[0]["expected_source"]

    for row in rows:
        key = (query_id, row["chunk_id"])
        previous = saved.get(key, {}).get("human_relevant", "").strip()
        if previous in {"0", "1"}:
            continue

        print("\n" + "-" * 70)
        print(f"{query_id} | Query: {query_text}")
        print(f"Expected source (initial label): {expected}")
        print(f"Rank: {row['rank']} / 5")
        print(f"Document: {row['source_filename']}")
        print(f"Pages: {row['page_start']}-{row['page_end']}")
        print(f"Cosine distance: {row['cosine_distance']}")
        print(f"Chunk ID: {row['chunk_id']}")
        print("\nChunk text:")
        print(row["chunk_text"][:900])

        while True:
            answer = input("\nRelevant? [y/n/s/q]: ").strip().lower()
            if answer in {"y", "n", "s", "q"}:
                break
            print("Enter y, n, s, or q.")

        if answer == "q":
            save()
            compute_metrics()
            raise SystemExit(0)

        if answer == "s":
            continue

        saved[key] = {
            "human_relevant": "1" if answer == "y" else "0",
            "review_notes": "",
        }
        save()

print("\nAll candidate results have been reviewed.")
compute_metrics()
