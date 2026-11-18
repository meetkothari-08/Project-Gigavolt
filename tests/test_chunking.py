import pytest

from gigavolt.chunking import (
    ChunkingConfig,
    DocumentChunker,
    choose_end,
    find_page_range,
    normalize_text,
    source_id_for,
)

SENTENCE = "The inverter fault was cleared after the firmware update was applied."  # 11 tokens


def make_pages(sentences_per_page=(30, 30, 10)):
    return [" ".join([SENTENCE] * n) for n in sentences_per_page]


def test_normalize_text_rejoins_hyphenation_and_collapses_space():
    raw = "tempera-\nture   limit\r\n\n\n\nnext\x00line"
    assert normalize_text(raw) == "temperature limit\n\nnext line"


def test_source_id_is_stable_16_hex():
    assert source_id_for("manuals/a.pdf") == source_id_for("manuals/a.pdf")
    assert len(source_id_for("manuals/a.pdf")) == 16


def test_choose_end_snaps_to_boundary_inside_backtrack_window():
    config = ChunkingConfig(chunk_tokens=100, boundary_backtrack_tokens=30)
    assert choose_end(0, 500, [40, 85, 120], config) == 85   # nearest boundary <= 100
    assert choose_end(0, 500, [40, 120], config) == 100      # none in [70, 100]
    assert choose_end(450, 500, [], config) == 500           # final chunk


def test_find_page_range_handles_cross_page_spans():
    spans = [(1, 0, 100), (2, 102, 200), (3, 202, 300)]
    assert find_page_range(90, 150, spans) == (1, 2)
    assert find_page_range(210, 250, spans) == (3, 3)


def test_chunks_respect_budget_overlap_and_sentences(fake_tokenizer):
    config = ChunkingConfig(chunk_tokens=60, overlap_tokens=10,
                            boundary_backtrack_tokens=15, start_boundary_tolerance=5)
    chunker = DocumentChunker(fake_tokenizer, config)
    _, chunks = chunker.chunk_document(make_pages(), "docs/test.pdf", "test.pdf")

    assert len(chunks) > 3
    assert all(c["token_count"] <= config.chunk_tokens for c in chunks)
    assert [c["chunk_index"] for c in chunks] == list(range(1, len(chunks) + 1))
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)

    for previous, current in zip(chunks, chunks[1:]):
        overlap = previous["token_end"] - current["token_start"]
        assert overlap == current["overlap_tokens_with_previous"]
        assert overlap >= config.overlap_tokens

    # Interior chunks end on a sentence boundary.
    assert all(c["chunk_text"].endswith(".") for c in chunks[:-1])
    # Pages are tracked and a chunk can span two pages.
    assert chunks[0]["page_start"] == 1 and chunks[-1]["page_end"] == 3
    assert any(c["page_end"] > c["page_start"] for c in chunks)


def test_chunk_ids_are_deterministic(fake_tokenizer):
    chunker = DocumentChunker(fake_tokenizer)
    first = chunker.chunk_document(make_pages(), "a.pdf", "a.pdf")
    second = chunker.chunk_document(make_pages(), "a.pdf", "a.pdf")
    assert first == second


def test_empty_document_produces_no_chunks(fake_tokenizer):
    assert DocumentChunker(fake_tokenizer).chunk_document(["", ""], "e.pdf", "e.pdf")[1] == []


def test_slow_tokenizer_is_rejected():
    class Slow:
        is_fast = False

    with pytest.raises(RuntimeError):
        DocumentChunker(Slow())
