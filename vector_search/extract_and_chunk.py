#!/usr/bin/env python3
"""Step 1 - Extract every PDF and split it into overlapping, sentence-aware chunks.

Outputs (in $GIGAVOLT_PROCESSED_DIR):
  extracted_pages.jsonl   one record per PDF page
  chunks.jsonl            one record per chunk, with source/page metadata
  summary.json            corpus, chunk-size and overlap statistics

    python vector_search/extract_and_chunk.py
"""

from __future__ import annotations

import json

from _common import (
    CHUNKS_FILE,
    DOCUMENTS_DIR,
    MODEL_NAME,
    PAGES_FILE,
    PROCESSED_DIR,
    SUMMARY_FILE,
)
from gigavolt.ingestion.documents.chunking import (
    DocumentChunker,
    extract_pdf_pages,
    source_id_for,
)
from gigavolt.ingestion.documents.pipeline import discover_pdfs


def stats(values: list[int]) -> dict:
    return {
        "min": min(values) if values else 0,
        "max": max(values) if values else 0,
        "average": round(sum(values) / len(values), 2) if values else 0,
    }


def main() -> None:
    if not DOCUMENTS_DIR.exists():
        raise FileNotFoundError(f"Missing directory: {DOCUMENTS_DIR}")

    pdf_files = discover_pdfs(DOCUMENTS_DIR)
    if not pdf_files:
        raise RuntimeError("No PDFs found.")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Loading tokenizer: {MODEL_NAME}")
    chunker = DocumentChunker.from_pretrained(MODEL_NAME)
    config = chunker.config

    total_pages = pages_with_text = 0
    low_text_pages, chunk_sizes, overlap_sizes, documents = [], [], [], []

    print(f"Found {len(pdf_files)} PDFs. Chunk target {config.chunk_tokens}, "
          f"overlap target {config.overlap_tokens}.\n")

    with PAGES_FILE.open("w", encoding="utf-8") as pages_out, \
         CHUNKS_FILE.open("w", encoding="utf-8") as chunks_out:
        for pdf_path in pdf_files:
            relative_path = pdf_path.relative_to(DOCUMENTS_DIR).as_posix()
            source_id = source_id_for(relative_path)
            page_texts = extract_pdf_pages(pdf_path)

            for page_number, text in enumerate(page_texts, start=1):
                total_pages += 1
                pages_with_text += bool(text)
                pages_out.write(json.dumps({
                    "source_id": source_id,
                    "source_filename": pdf_path.name,
                    "source_path": relative_path,
                    "page_number": page_number,
                    "character_count": len(text),
                    "text": text,
                }, ensure_ascii=False) + "\n")
                if len(text) < 30:
                    low_text_pages.append({
                        "source_filename": pdf_path.name,
                        "page_number": page_number,
                        "character_count": len(text),
                    })

            _, records = chunker.chunk_document(page_texts, relative_path, pdf_path.name)
            for record in records:
                chunks_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                chunk_sizes.append(record["token_count"])
                if record["chunk_index"] > 1:
                    overlap_sizes.append(record["overlap_tokens_with_previous"])

            documents.append({
                "source_filename": pdf_path.name,
                "source_path": relative_path,
                "pages": len(page_texts),
                "chunks": len(records),
            })
            crossing = sum(r["page_end"] > r["page_start"] for r in records)
            print(f"Processed: {pdf_path.name} | pages={len(page_texts)} | "
                  f"chunks={len(records)} | chunks crossing pages={crossing}")

    summary = {
        "source_directory": DOCUMENTS_DIR.name,
        "tokenizer_model": MODEL_NAME,
        "target_chunk_tokens": config.chunk_tokens,
        "target_overlap_tokens": config.overlap_tokens,
        "pdf_count": len(pdf_files),
        "total_pages": total_pages,
        "pages_with_text": pages_with_text,
        "total_chunks": len(chunk_sizes),
        "chunk_token_statistics": stats(chunk_sizes),
        "overlap_statistics": {
            "adjacent_pairs": len(overlap_sizes),
            **stats(overlap_sizes),
            "pairs_with_at_least_25_tokens": sum(size >= 25 for size in overlap_sizes),
        },
        "low_text_pages": low_text_pages,
        "documents": documents,
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nPDFs: {len(pdf_files)} | pages: {total_pages} | "
          f"pages with text: {pages_with_text} | chunks: {len(chunk_sizes)}")
    print(f"Chunk tokens: {summary['chunk_token_statistics']}")
    print(f"Overlap: {summary['overlap_statistics']}")
    print(f"Wrote {PAGES_FILE}, {CHUNKS_FILE}, {SUMMARY_FILE}")


if __name__ == "__main__":
    main()
