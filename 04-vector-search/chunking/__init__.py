"""Sentence-aware, token-budgeted document chunking (installed as ``gigavolt.chunking``)."""

from gigavolt.chunking.chunker import (
    PAGE_SEPARATOR,
    ChunkingConfig,
    DocumentChunker,
    choose_end,
    choose_next_start,
    extract_pdf_pages,
    find_page_range,
    find_sentence_boundaries,
    normalize_text,
    source_id_for,
)

__all__ = [
    "PAGE_SEPARATOR",
    "ChunkingConfig",
    "DocumentChunker",
    "choose_end",
    "choose_next_start",
    "extract_pdf_pages",
    "find_page_range",
    "find_sentence_boundaries",
    "normalize_text",
    "source_id_for",
]
