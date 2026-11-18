#!/usr/bin/env python3
"""End-to-end RAG benchmark: 20 questions, latency percentiles, citation audit.

Writes ``benchmark_<timestamp>.csv`` (one row per question) and
``summary_<timestamp>.json`` to ``06-automation/results/``.

    python 06-automation/benchmark/rag_benchmark.py
"""

from __future__ import annotations

import csv
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from gigavolt.rag.pipeline import GigavoltRAGPipeline

RESULT_DIR = Path(__file__).resolve().parents[1] / "results"

# Covers document lookup, safety procedures, supplier/inventory questions,
# model-level telemetry and multi-source synthesis.
BENCHMARK_QUESTIONS = [
    "What are the documented warranty requirements for equipment?",
    "What procedures should technicians follow when investigating a field failure?",
    "What are the important safety precautions during equipment maintenance?",
    "What documentation describes inverter firmware requirements?",
    "What are the documented procedures for temperature and voltage calibration?",
    "What information is available about emergency response procedures?",
    "What are the documented requirements for battery management system maintenance?",
    "What does the documentation say about equipment commissioning?",
    "What supplier risks are documented for lithium cell components?",
    "Which lithium cell components and suppliers are listed in the database?",
    "Which inventory parts are currently below their reorder levels?",
    "What parts have low stock and may require replenishment?",
    "What diagnostic information is available for the X-7000 model?",
    "Are there high-temperature telemetry observations for the X-7000?",
    "What fault conditions have been recorded for the X-7000?",
    "What technical documentation could help investigate an electrical fault?",
    "What information is available about equipment warranty claims?",
    "How can maintenance history help investigate recurring equipment failures?",
    "What evidence is available about supplier quality and inspection requirements?",
    "Summarize the available technical documentation, maintenance information, "
    "and telemetry relevant to equipment reliability.",
]


def percentile(values: list[float], percent: float) -> float:
    """Linear-interpolated percentile (same method as numpy's default)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def latency_stats(values: list[float]) -> dict:
    return {
        "mean": statistics.fmean(values) if values else 0.0,
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


def rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def main() -> None:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULT_DIR / f"benchmark_{timestamp}.csv"
    summary_path = RESULT_DIR / f"summary_{timestamp}.json"

    pipeline = GigavoltRAGPipeline()
    rows: list[dict] = []
    total = len(BENCHMARK_QUESTIONS)

    print(f"Gigavolt RAG benchmark: {total} questions\n")
    benchmark_start = time.perf_counter()

    try:
        for index, question in enumerate(BENCHMARK_QUESTIONS, start=1):
            print(f"[{index}/{total}] {question}")
            row = {
                "question_id": index,
                "question": question,
                "status": "failed",
                "latency_seconds": None,
                "retrieval_seconds": None,
                "generation_seconds": None,
                "documents": 0,
                "mariadb_records": 0,
                "mongodb_records": 0,
                "citations_present": False,
                "all_citations_valid": False,
                "fallback_used": False,
                "model_citations_present": False,
                "model_citations_all_valid": False,
                "model_citations_invalid": "",
                "retrieval_errors": "",
                "answer": "",
                "model": "",
            }
            try:
                result = pipeline.ask(question)
                provenance = result["provenance"]
                sources = result["sources"]
                row.update({
                    "status": "success",
                    "latency_seconds": float(result["latency_seconds"]),
                    "retrieval_seconds": float(result["retrieval_seconds"]),
                    "generation_seconds": float(result.get("generation_seconds") or 0),
                    "documents": sources["documents"],
                    "mariadb_records": sources["mariadb"],
                    "mongodb_records": sources["mongodb"],
                    "citations_present": provenance["citations_present"],
                    "all_citations_valid": provenance["all_citations_valid"],
                    "fallback_used": provenance["fallback_used"],
                    "model_citations_present": provenance["model_citations_present"],
                    "model_citations_all_valid": provenance["model_citations_all_valid"],
                    "model_citations_invalid": json.dumps(provenance["model_citations_invalid"]),
                    "retrieval_errors": json.dumps(result["errors"]),
                    "answer": result["answer"],
                    "model": result["model"],
                })
                print(
                    f"  total {row['latency_seconds']:.2f}s | "
                    f"retrieval {row['retrieval_seconds']:.3f}s | "
                    f"generation {row['generation_seconds']:.2f}s"
                )
            except Exception as exc:  # noqa: BLE001 - recorded per question
                row["retrieval_errors"] = str(exc)
                print(f"  FAILED: {exc}")
            rows.append(row)
    finally:
        pipeline.close()

    elapsed = time.perf_counter() - benchmark_start
    ok = [row for row in rows if row["status"] == "success"]
    n = len(ok)

    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_questions": total,
        "successful_requests": n,
        "failed_requests": total - n,
        "requests_with_retrieval_errors": sum(
            1 for row in ok if row["retrieval_errors"] not in ("", "[]")
        ),
        "latency_seconds": {
            "end_to_end": latency_stats([row["latency_seconds"] for row in ok]),
            "retrieval": latency_stats([row["retrieval_seconds"] for row in ok]),
            "generation": latency_stats([row["generation_seconds"] for row in ok]),
        },
        "throughput_requests_per_second": rate(n, elapsed),
        "citation_presence_rate": rate(sum(row["citations_present"] for row in ok), n),
        "valid_citation_rate": rate(sum(row["all_citations_valid"] for row in ok), n),
        "fallback_rate": rate(sum(row["fallback_used"] for row in ok), n),
        "model_citation_presence_rate": rate(
            sum(row["model_citations_present"] for row in ok), n
        ),
        "model_valid_citation_rate": rate(
            sum(row["model_citations_all_valid"] for row in ok), n
        ),
        "total_execution_seconds": elapsed,
    }

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\nSummary")
    print(json.dumps(summary, indent=2))
    print(f"\nSaved {csv_path}\nSaved {summary_path}")


if __name__ == "__main__":
    main()
