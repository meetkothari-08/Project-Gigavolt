#!/usr/bin/env python3
"""Re-audit citations in a saved benchmark CSV without calling the LLM.

The original benchmark scored citations over the whole answer, including the
``Retrieved Sources:`` list the generator appends when the model cites
nothing. This audit separates what the *model* wrote from that fallback and
classifies every bracketed token:

* ``source_id``   - well-formed ID (document chunk ID or ``prefix:value``)
* ``not_an_id``   - prose or copied evidence inside brackets

Optionally, chunk IDs are checked against ``chunks.jsonl`` so a well-formed
but non-existent document ID is caught.

    cd m6-ops-evaluation
    python benchmark/audit_saved_answers.py results/benchmark_20261115_075228.csv
    python benchmark/audit_saved_answers.py <csv> --chunks ../data/processed/chunks.jsonl --json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from gigavolt.rag.provenance import extract_citations, split_answer

CHUNK_ID = re.compile(r"^[0-9a-f]{16}-c\d{4}$")
PREFIXED_ID = re.compile(r"^(equipment|dispatch|warranty|part|telemetry|fault):[A-Za-z0-9_-]+$")


def classify(token: str) -> str:
    return "source_id" if CHUNK_ID.match(token) or PREFIXED_ID.match(token) else "not_an_id"


def load_chunk_ids(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    with path.open(encoding="utf-8") as handle:
        return {json.loads(line)["chunk_id"] for line in handle if line.strip()}


def audit(csv_path: Path, known_chunks: set[str] | None) -> dict:
    with csv_path.open(encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("status") == "success"]

    per_question = []
    for row in rows:
        model_text, fallback = split_answer(row["answer"])
        tokens = sorted(extract_citations(model_text))
        ids = [t for t in tokens if classify(t) == "source_id"]
        prose = [t for t in tokens if classify(t) == "not_an_id"]
        unknown_chunks = (
            [t for t in ids if CHUNK_ID.match(t) and t not in known_chunks]
            if known_chunks is not None else []
        )
        per_question.append({
            "question_id": int(row["question_id"]),
            "fallback_used": bool(fallback),
            "model_tokens": len(tokens),
            "model_source_ids": ids,
            "model_non_id_brackets": len(prose),
            "unknown_chunk_ids": unknown_chunks,
            "clean_model_citations": bool(ids) and not prose and not unknown_chunks,
        })

    n = len(per_question)
    return {
        "file": csv_path.name,
        "answers": n,
        "fallback_used": sum(q["fallback_used"] for q in per_question),
        "answers_with_any_model_brackets": sum(q["model_tokens"] > 0 for q in per_question),
        "answers_with_model_source_ids": sum(bool(q["model_source_ids"]) for q in per_question),
        "answers_with_non_id_brackets": sum(q["model_non_id_brackets"] > 0 for q in per_question),
        "answers_with_only_clean_model_citations": sum(
            q["clean_model_citations"] for q in per_question
        ),
        "per_question": per_question,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", type=Path)
    parser.add_argument("--chunks", type=Path, help="chunks.jsonl to verify document IDs")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = audit(args.csv, load_chunk_ids(args.chunks))
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
        return 0

    n = report["answers"]
    print(f"{report['file']}: {n} answers")
    for key in (
        "fallback_used",
        "answers_with_any_model_brackets",
        "answers_with_model_source_ids",
        "answers_with_non_id_brackets",
        "answers_with_only_clean_model_citations",
    ):
        print(f"  {key:42s} {report[key]:>3}/{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
