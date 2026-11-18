"""Sentence-aware, token-budgeted chunking of whole PDF documents.

Each PDF is processed as one continuous text (pages joined by a blank line)
so chunks can cross page boundaries while keeping a mapping back to the
source pages. Chunks are sized in *model tokens* (the embedding model's own
tokenizer), never exceed ``chunk_tokens``, and overlap the previous chunk by
about ``overlap_tokens``. Boundaries snap to the nearest sentence or line
break within a small backtrack window so chunks rarely split mid-sentence.

Used by both the batch corpus build (``04-vector-search/scripts/extract_and_chunk.py``)
and the incremental document pipeline, so the two always agree on chunk IDs.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

PAGE_SEPARATOR = "\n\n"
SENTENCE_OR_LINE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_tokens: int = 300
    overlap_tokens: int = 50
    boundary_backtrack_tokens: int = 30
    start_boundary_tolerance: int = 15


def normalize_text(text: str) -> str:
    """Clean common PDF extraction artifacts without removing technical notation."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\x00", " ")
    # Re-join words hyphenated across a line break ("tempera-\nture").
    text = re.sub(r"(?<=[a-z])-\s*\n\s*(?=[a-z])", "", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def source_id_for(relative_path: str) -> str:
    """Stable 16-hex-character document ID derived from its relative path."""
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]


def extract_pdf_pages(pdf_path: Path) -> list[str]:
    """Return normalized text for each page of a PDF (requires PyMuPDF)."""
    import fitz  # PyMuPDF

    with fitz.open(pdf_path) as pdf:
        return [normalize_text(page.get_text("text", sort=True)) for page in pdf]


def find_sentence_boundaries(text: str, token_offsets: list[tuple[int, int]]) -> list[int]:
    """Token indices that start right after a sentence end or line break."""
    token_ends = [end for _, end in token_offsets]
    result = set()
    for match in SENTENCE_OR_LINE_BREAK.finditer(text):
        index = bisect_right(token_ends, match.end())
        if 0 < index < len(token_offsets):
            result.add(index)
    return sorted(result)


def choose_end(start: int, total: int, boundaries: list[int], config: ChunkingConfig) -> int:
    """Prefer a sentence boundary close to the token budget without exceeding it."""
    target = min(start + config.chunk_tokens, total)
    if target == total:
        return target
    earliest = max(start + 1, target - config.boundary_backtrack_tokens)
    candidates = boundaries[bisect_left(boundaries, earliest):bisect_right(boundaries, target)]
    return candidates[-1] if candidates else target


def choose_next_start(start: int, end: int, boundaries: list[int], config: ChunkingConfig) -> int:
    """Start the next chunk ~overlap tokens back, snapping to an earlier boundary if near."""
    desired = max(start + 1, end - config.overlap_tokens)
    earliest = max(start + 1, desired - config.start_boundary_tolerance)
    candidates = boundaries[bisect_left(boundaries, earliest):bisect_right(boundaries, desired)]
    return candidates[-1] if candidates else desired


def find_page_range(char_start: int, char_end: int,
                    page_spans: list[tuple[int, int, int]]) -> tuple[int, int]:
    """First and last page whose text intersects the character span."""
    pages = [page for page, start, end in page_spans if start < char_end and end > char_start]
    if not pages:
        nearest = min(page_spans, key=lambda item: abs(item[1] - char_start))
        return nearest[0], nearest[0]
    return pages[0], pages[-1]


class DocumentChunker:
    """Split documents into overlapping, sentence-aligned token windows.

    ``tokenizer`` must be a Hugging Face *fast* tokenizer (offset mapping is
    required to map tokens back to characters).
    """

    def __init__(self, tokenizer, config: ChunkingConfig | None = None):
        if not getattr(tokenizer, "is_fast", False):
            raise RuntimeError("A fast tokenizer is required.")
        self.tokenizer = tokenizer
        self.config = config or ChunkingConfig()

    @classmethod
    def from_pretrained(cls, model_name: str, config: ChunkingConfig | None = None):
        from transformers import AutoTokenizer

        return cls(AutoTokenizer.from_pretrained(model_name, use_fast=True), config)

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False, truncation=False))

    def split(self, page_texts: list[str]) -> list[dict]:
        """Chunk one document given its page texts. Returns raw chunk spans."""
        full_text = PAGE_SEPARATOR.join(page_texts)
        if not full_text.strip():
            return []

        page_spans = []
        cursor = 0
        for page_number, text in enumerate(page_texts, start=1):
            if text:
                page_spans.append((page_number, cursor, cursor + len(text)))
            cursor += len(text) + len(PAGE_SEPARATOR)

        encoded = self.tokenizer(
            full_text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        offsets = [tuple(offset) for offset in encoded["offset_mapping"]]
        total = len(offsets)
        if total == 0:
            return []

        boundaries = find_sentence_boundaries(full_text, offsets)
        chunks: list[dict] = []
        start = 0

        while start < total:
            end = choose_end(start, total, boundaries, self.config)

            # Re-tokenize the candidate span on its own: tokenization at a
            # substring edge can differ slightly, so shrink until it fits.
            while end > start:
                chunk_text = full_text[offsets[start][0]:offsets[end - 1][1]].strip()
                token_count = self.count_tokens(chunk_text)
                if chunk_text and token_count <= self.config.chunk_tokens:
                    break
                end -= 1

            if end <= start:
                raise RuntimeError("Could not create a chunk within the token budget")

            char_start, char_end = offsets[start][0], offsets[end - 1][1]
            page_start, page_end = find_page_range(char_start, char_end, page_spans)
            chunks.append({
                "start_token": start,
                "end_token": end,
                "char_start": char_start,
                "char_end": char_end,
                "page_start": page_start,
                "page_end": page_end,
                "chunk_text": full_text[char_start:char_end].strip(),
                "token_count": token_count,
            })

            if end >= total:
                break
            start = max(start + 1, choose_next_start(start, end, boundaries, self.config))

        return chunks

    def chunk_document(self, page_texts: list[str], relative_path: str,
                       filename: str) -> tuple[str, list[dict]]:
        """Chunk a document and attach stable IDs and source metadata."""
        source_id = source_id_for(relative_path)
        spans = self.split(page_texts)
        records = []
        per_page = defaultdict(int)

        for index, span in enumerate(spans, start=1):
            per_page[span["page_start"]] += 1
            previous_end = spans[index - 2]["end_token"] if index > 1 else None
            overlap = max(0, previous_end - span["start_token"]) if previous_end is not None else 0

            records.append({
                "chunk_id": f"{source_id}-c{index:04d}",
                "source_id": source_id,
                "source_filename": filename,
                "source_path": relative_path,
                "page_number": span["page_start"],
                "page_start": span["page_start"],
                "page_end": span["page_end"],
                "chunk_index": index,
                "chunk_index_on_page": per_page[span["page_start"]],
                "token_start": span["start_token"],
                "token_end": span["end_token"],
                "overlap_tokens_with_previous": overlap,
                "token_count": span["token_count"],
                "chunk_text": span["chunk_text"],
            })

        return source_id, records
