"""Incremental document ingestion with fake embedder and an in-memory vector store."""

import numpy as np
import pytest

from gigavolt.ingestion.documents import pipeline as pipeline_module
from gigavolt.ingestion.documents.chunking import DocumentChunker
from gigavolt.ingestion.documents.pipeline import (
    DocumentIndexer,
    DocumentPipeline,
    DocumentState,
)


class FakeCollection:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def count(self):
        return len(self.items)

    def get(self, where, include):
        ids = [i for i, item in self.items.items()
               if item["metadata"]["source_id"] == where["source_id"]]
        return {"ids": ids}

    def upsert(self, ids, documents, embeddings, metadatas):
        for i, doc, meta in zip(ids, documents, metadatas):
            self.items[i] = {"document": doc, "metadata": meta}

    def delete(self, ids):
        for i in ids:
            self.items.pop(i, None)


class FakeEmbedder:
    def embed(self, chunks):
        return np.ones((len(chunks), 384), dtype=np.float32)


@pytest.fixture
def setup(tmp_path, fake_tokenizer, monkeypatch):
    # Each "PDF" is a text file; pages are separated by form feeds.
    monkeypatch.setattr(
        pipeline_module, "extract_pdf_pages",
        lambda path: path.read_text().split("\f"),
    )
    docs = tmp_path / "documents"
    docs.mkdir()
    collection = FakeCollection()

    def make():
        return DocumentPipeline(
            apply=True,
            source_dir=docs,
            state=DocumentState(tmp_path / "state.db"),
            chunker=DocumentChunker(fake_tokenizer),
            embedder=FakeEmbedder(),
            indexer=DocumentIndexer(collection=collection),
        )

    return docs, collection, make


def run(make):
    pipeline = make()
    try:
        return pipeline.run()
    finally:
        pipeline.close()


def test_add_skip_modify_delete_cycle(setup):
    docs, collection, make = setup
    words = " ".join(["Battery cell voltage nominal."] * 200)
    (docs / "manual.pdf").write_text(words)

    first = run(make)
    assert first["new"] == 1 and first["chunks_indexed"] > 1
    indexed = collection.count()
    assert indexed == first["chunks_indexed"]

    second = run(make)
    assert second["unchanged"] == 1 and second["chunks_indexed"] == 0
    assert collection.count() == indexed

    # A shorter revision: obsolete chunk IDs must be removed after the upsert.
    (docs / "manual.pdf").write_text("Battery cell voltage nominal. Revised.")
    third = run(make)
    assert third["modified"] == 1
    assert collection.count() == 1

    (docs / "temp.pdf").write_text(words)
    run(make)
    assert collection.count() == 1 + indexed

    (docs / "temp.pdf").unlink()
    fifth = run(make)
    assert fifth["deleted"] == 1
    assert collection.count() == 1


def test_empty_folder_does_not_purge_collection(setup):
    docs, collection, make = setup
    (docs / "manual.pdf").write_text("Battery cell voltage nominal.")
    run(make)
    (docs / "manual.pdf").unlink()

    summary = run(make)
    assert summary["deleted"] == 0
    assert collection.count() == 1


def test_document_without_text_is_counted_as_failed(setup):
    docs, collection, make = setup
    (docs / "scan.pdf").write_text("")
    summary = run(make)
    assert summary["failed"] == 1 and collection.count() == 0
