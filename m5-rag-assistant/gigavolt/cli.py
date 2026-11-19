"""Command-line interface for the Gigavolt RAG assistant.

    gigavolt-ask                                   # interactive session
    gigavolt-ask "Service history for EQ-5508?"    # single question
    gigavolt-ask --json "..."                      # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from gigavolt.rag.engine import HybridRAGEngine


def print_result(result: dict) -> None:
    provenance = result["provenance"]
    print("\n--- ANSWER ---")
    print(result["answer"])
    print("\n--- RETRIEVAL ---")
    print(", ".join(f"{name}: {count}" for name, count in result["sources"].items()))
    print("\n--- PROVENANCE ---")
    print("Model-written citations valid:", provenance["model_citations_valid"])
    print("Model-written citations invalid:", provenance["model_citations_invalid"])
    print("Fallback source list appended:", provenance["fallback_used"])
    print("\n--- PERFORMANCE ---")
    print(f"Model: {result['model']}")
    print(
        f"Latency: {result['latency_seconds']} s "
        f"(retrieval {result['retrieval_seconds']} s, "
        f"generation {result['generation_seconds']} s)"
    )
    if result["errors"]:
        print("\n--- RETRIEVAL ERRORS ---")
        for error in result["errors"]:
            print(f"{error['source']}: {error['error']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask the Gigavolt hybrid RAG assistant.")
    parser.add_argument("question", nargs="*", help="Question to ask (omit for interactive mode)")
    parser.add_argument("--json", action="store_true", help="Print the full result as JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    pipeline = HybridRAGEngine()
    try:
        if args.question:
            result = pipeline.ask(" ".join(args.question))
            if args.json:
                json.dump(result, sys.stdout, indent=2, default=str)
                print()
            else:
                print_result(result)
            return 0

        print("Gigavolt RAG assistant. Type 'exit' to quit.")
        while True:
            try:
                question = input("\nAsk Gigavolt: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if question.lower() in {"exit", "quit"}:
                break
            if not question:
                continue
            try:
                print_result(pipeline.ask(question))
            except Exception as exc:  # noqa: BLE001 - keep the session alive
                print(f"\nError: {exc}")
        return 0
    finally:
        pipeline.close()


if __name__ == "__main__":
    sys.exit(main())
