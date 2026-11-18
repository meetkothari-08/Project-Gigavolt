#!/usr/bin/env python3
"""Step 2 - Validate chunks.jsonl: unique IDs, consecutive indexes, token budget,
valid token/page ranges and the overlap recorded between adjacent chunks.

    python 04-vector-search/scripts/validate_chunks.py
"""

import json
import sys
from collections import defaultdict

from _common import CHUNKS_FILE, SUMMARY_FILE

summary = json.loads(SUMMARY_FILE.read_text(encoding="utf-8"))
target = summary["target_chunk_tokens"]
target_overlap = summary["target_overlap_tokens"]

chunks = []
with CHUNKS_FILE.open(encoding="utf-8") as f:
    for line in f:
        if line.strip():
            chunks.append(json.loads(line))

documents = defaultdict(list)
issues = []

for chunk in chunks:
    required = [
        "chunk_id", "source_path", "chunk_index",
        "token_start", "token_end", "token_count",
        "overlap_tokens_with_previous", "chunk_text",
        "page_start", "page_end",
    ]

    missing = [k for k in required if k not in chunk]
    if missing:
        issues.append(f"Missing fields in chunk: {missing}")
        continue

    documents[chunk["source_path"]].append(chunk)

ids = [c["chunk_id"] for c in chunks]

if len(ids) != len(set(ids)):
    issues.append("Duplicate chunk IDs found.")

sizes = []
overlaps = []
checked_pairs = 0

for source_path, items in documents.items():
    items.sort(key=lambda c: c["chunk_index"])

    expected_indexes = list(range(1, len(items) + 1))
    actual_indexes = [c["chunk_index"] for c in items]

    if actual_indexes != expected_indexes:
        issues.append(f"{source_path}: nonconsecutive chunk indexes.")

    for i, chunk in enumerate(items):
        size = chunk["token_count"]
        sizes.append(size)

        if size > target:
            issues.append(
                f"{chunk['chunk_id']}: {size} tokens exceeds {target}."
            )

        if chunk["token_end"] <= chunk["token_start"]:
            issues.append(f"{chunk['chunk_id']}: invalid token range.")

        if chunk["page_start"] > chunk["page_end"]:
            issues.append(f"{chunk['chunk_id']}: invalid page range.")

        if i == 0:
            continue

        previous = items[i - 1]

        # Both chunks' offsets refer to the same full-document
        # token sequence. This is the correct overlap calculation
        # for the current document-level chunker.
        overlap = previous["token_end"] - chunk["token_start"]
        recorded = chunk["overlap_tokens_with_previous"]

        checked_pairs += 1
        overlaps.append(overlap)

        if overlap != recorded:
            issues.append(
                f"{chunk['chunk_id']}: recorded overlap {recorded}, "
                f"calculated overlap {overlap}."
            )

        if overlap < target_overlap:
            issues.append(
                f"{chunk['chunk_id']}: overlap {overlap} is below "
                f"the target {target_overlap}."
            )

print("=" * 60)
print("DOCUMENT-LEVEL CHUNK VALIDATION")
print("=" * 60)
print(f"PDF documents represented: {len(documents)}")
print(f"Total chunks:               {len(chunks)}")
print(f"Unique IDs:                 {len(set(ids))}")
print(f"Chunk target:               {target}")
print(f"Overlap target:             {target_overlap}")
print(f"Chunks over target:         {sum(s > target for s in sizes)}")

if sizes:
    print(f"Chunk size min/max:         {min(sizes)} / {max(sizes)}")
    print(f"Chunk size average:         {sum(sizes) / len(sizes):.1f}")

print(f"Adjacent pairs checked:     {checked_pairs}")

if overlaps:
    print(f"Overlap min/max:            {min(overlaps)} / {max(overlaps)}")
    print(f"Overlap average:            {sum(overlaps) / len(overlaps):.1f}")
    print(
        f"Pairs meeting overlap target: "
        f"{sum(o >= target_overlap for o in overlaps)}/{len(overlaps)}"
    )

print("\nValidation issues:")
if issues:
    for issue in issues:
        print(" -", issue)
else:
    print("None")

print("\nRESULT:", "PASS" if not issues else "NEEDS FIXING")
sys.exit(0 if not issues else 1)
