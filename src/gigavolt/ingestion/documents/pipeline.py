"""Incremental document ingestion into ChromaDB.

For every PDF under the documents directory:

* unchanged (same SHA-256 as last run)  -> skipped
* new or modified                       -> extract, chunk, embed, upsert,
                                           then delete obsolete chunk IDs
* deleted from disk                     -> its vectors are removed

State is committed to SQLite only after ChromaDB accepts the write, so an
interrupted run is retried on the next run instead of being marked done.

    python -m gigavolt.ingestion.documents.pipeline            # dry run
    python -m gigavolt.ingestion.documents.pipeline --apply    # write to ChromaDB
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from gigavolt.config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, get_settings
from gigavolt.ingestion.documents.chunking import DocumentChunker, extract_pdf_pages
from gigavolt.logging_setup import configure_logging

BATCH_SIZE = 32

logger = logging.getLogger("gigavolt.document_pipeline")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_pdfs(source_dir: Path) -> list[Path]:
    return sorted(
        path for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


class DocumentState:
    """Per-document file hash and chunk count, persisted in SQLite (WAL mode)."""

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = get_settings().paths.state_dir / "document_state.db"
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(db_path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                source_path  TEXT PRIMARY KEY,
                source_id    TEXT NOT NULL,
                file_hash    TEXT NOT NULL,
                chunk_count  INTEGER NOT NULL,
                status       TEXT NOT NULL,
                processed_at TEXT
            )
        """)
        self.connection.commit()

    def get(self, source_path: str):
        return self.connection.execute(
            "SELECT source_id, file_hash, chunk_count, status FROM documents WHERE source_path = ?",
            (source_path,),
        ).fetchone()

    def save(self, source_path: str, source_id: str, file_hash: str, chunk_count: int) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO documents
                    (source_path, source_id, file_hash, chunk_count, status, processed_at)
                VALUES (?, ?, ?, ?, 'processed', ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    source_id    = excluded.source_id,
                    file_hash    = excluded.file_hash,
                    chunk_count  = excluded.chunk_count,
                    status       = 'processed',
                    processed_at = excluded.processed_at
                """,
                (source_path, source_id, file_hash, chunk_count,
                 datetime.now(timezone.utc).isoformat()),
            )

    def list_all(self) -> list[tuple[str, str]]:
        return self.connection.execute("SELECT source_path, source_id FROM documents").fetchall()

    def delete(self, source_path: str) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM documents WHERE source_path = ?", (source_path,))

    def close(self) -> None:
        self.connection.close()


class DocumentEmbedder:
    """E5 passage embeddings, L2-normalized, validated for shape and finiteness."""

    def __init__(self, model_name: str = EMBEDDING_MODEL):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name, device="cpu")
        if self.model.get_sentence_embedding_dimension() != EMBEDDING_DIMENSIONS:
            raise RuntimeError("Unexpected embedding dimension.")

    def embed(self, chunks: list[dict]):
        import numpy as np

        vectors = self.model.encode(
            ["passage: " + item["chunk_text"] for item in chunks],
            batch_size=BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        if vectors.shape != (len(chunks), EMBEDDING_DIMENSIONS):
            raise RuntimeError(f"Unexpected embedding shape: {vectors.shape}")
        if not np.isfinite(vectors).all():
            raise RuntimeError("Non-finite embedding values found.")
        return vectors


class DocumentIndexer:
    """Writes chunk vectors into the existing ChromaDB collection."""

    def __init__(self, collection=None):
        if collection is None:
            import chromadb

            settings = get_settings()
            client = chromadb.PersistentClient(path=str(settings.paths.chroma_dir))
            collection = client.get_collection(name=settings.vector.collection)

            metadata = collection.metadata or {}
            if metadata.get("embedding_model") != EMBEDDING_MODEL:
                raise RuntimeError("Collection embedding model does not match.")
            if metadata.get("embedding_dimensions") != EMBEDDING_DIMENSIONS:
                raise RuntimeError("Collection embedding dimensions do not match.")

        self.collection = collection

    def _ids_for_source(self, source_id: str) -> list[str]:
        return self.collection.get(where={"source_id": source_id}, include=["metadatas"])["ids"]

    def delete_document(self, source_id: str) -> int:
        ids = self._ids_for_source(source_id)
        for start in range(0, len(ids), BATCH_SIZE):
            self.collection.delete(ids=ids[start:start + BATCH_SIZE])
        return len(ids)

    def replace_document(self, source_id: str, chunks: list[dict], vectors) -> tuple[int, int]:
        """Upsert new chunks first, then delete chunk IDs that no longer exist."""
        old_ids = set(self._ids_for_source(source_id))
        indexed_at = datetime.now(timezone.utc).isoformat()

        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start:start + BATCH_SIZE]
            self.collection.upsert(
                ids=[item["chunk_id"] for item in batch],
                documents=[item["chunk_text"] for item in batch],
                embeddings=vectors[start:start + BATCH_SIZE].tolist(),
                metadatas=[
                    {key: value for key, value in item.items() if key != "chunk_text"}
                    | {"embedding_model": EMBEDDING_MODEL, "indexed_at": indexed_at}
                    for item in batch
                ],
            )

        obsolete = sorted(old_ids - {item["chunk_id"] for item in chunks})
        for start in range(0, len(obsolete), BATCH_SIZE):
            self.collection.delete(ids=obsolete[start:start + BATCH_SIZE])

        return len(old_ids), len(obsolete)


class DocumentPipeline:
    """Detect new, modified and deleted PDFs and keep ChromaDB in sync."""

    def __init__(self, apply: bool = False, source_dir: Path | None = None,
                 state: DocumentState | None = None, chunker: DocumentChunker | None = None,
                 embedder: DocumentEmbedder | None = None,
                 indexer: DocumentIndexer | None = None):
        self.apply = apply
        self.source_dir = source_dir or get_settings().paths.documents_dir
        self.state = state or DocumentState()
        logger.info("Loading tokenizer and embedding model: %s", EMBEDDING_MODEL)
        self.chunker = chunker or DocumentChunker.from_pretrained(EMBEDDING_MODEL)
        self.embedder = embedder or DocumentEmbedder()
        self.indexer = indexer or DocumentIndexer()

    def _process(self, pdf_path: Path, relative_path: str):
        source_id, chunks = self.chunker.chunk_document(
            extract_pdf_pages(pdf_path), relative_path, pdf_path.name
        )
        if not chunks:
            raise ValueError(
                f"No extractable text in {relative_path}. Scanned PDFs may require OCR."
            )
        return source_id, chunks, self.embedder.embed(chunks)

    def run(self) -> dict:
        if not self.source_dir.exists():
            raise FileNotFoundError(f"Incoming document directory not found: {self.source_dir}")

        pdf_files = discover_pdfs(self.source_dir)
        summary = {
            "discovered": len(pdf_files),
            "new": 0,
            "modified": 0,
            "unchanged": 0,
            "deleted": 0,
            "failed": 0,
            "chunks_indexed": 0,
        }

        logger.info("Starting document ingestion (apply=%s)", self.apply)
        logger.info("PDF files discovered: %s", len(pdf_files))
        logger.info("Existing collection count: %s", self.indexer.collection.count())

        for pdf_path in pdf_files:
            relative_path = pdf_path.relative_to(self.source_dir).as_posix()
            try:
                file_hash = file_sha256(pdf_path)
                previous = self.state.get(relative_path)

                if previous and previous[1] == file_hash:
                    summary["unchanged"] += 1
                    logger.info("UNCHANGED: %s", relative_path)
                    continue

                change_type = "MODIFIED" if previous else "NEW"
                summary[change_type.lower()] += 1
                logger.info("%s: %s", change_type, relative_path)

                source_id, chunks, vectors = self._process(pdf_path, relative_path)
                logger.info("Prepared %s chunks for %s", len(chunks), relative_path)

                if not self.apply:
                    continue

                old_count, obsolete_count = self.indexer.replace_document(
                    source_id, chunks, vectors
                )
                # Commit state only after ChromaDB accepted the write.
                self.state.save(relative_path, source_id, file_hash, len(chunks))
                summary["chunks_indexed"] += len(chunks)
                logger.info(
                    "INDEXED: %s | new chunks=%s | previous chunks=%s | obsolete removed=%s",
                    relative_path, len(chunks), old_count, obsolete_count,
                )
            except Exception:
                summary["failed"] += 1
                logger.exception("FAILED: %s", relative_path)

        if self.apply:
            self._reconcile_deletions(pdf_files, summary)

        logger.info("Document pipeline summary: %s", summary)
        logger.info("Final ChromaDB count: %s", self.indexer.collection.count())
        return summary

    def _reconcile_deletions(self, pdf_files: list[Path], summary: dict) -> None:
        """Remove vectors for documents that disappeared from the source folder."""
        if not pdf_files:
            # An empty folder is more likely a mount problem than a real purge.
            logger.warning(
                "No PDFs found. Skipping deletion reconciliation to protect the collection."
            )
            return

        current = {path.relative_to(self.source_dir).as_posix() for path in pdf_files}
        for stored_path, stored_source_id in self.state.list_all():
            if stored_path in current:
                continue
            try:
                removed = self.indexer.delete_document(stored_source_id)
                self.state.delete(stored_path)  # only after vectors are gone
                summary["deleted"] += 1
                logger.info("DELETED: %s | removed vectors=%s", stored_path, removed)
            except Exception:
                summary["failed"] += 1
                logger.exception("FAILED TO DELETE: %s", stored_path)

    def close(self) -> None:
        self.state.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gigavolt incremental document ingestion")
    parser.add_argument(
        "--apply", action="store_true", help="Write processed document chunks to ChromaDB"
    )
    args = parser.parse_args(argv)

    configure_logging("document_pipeline.log")
    pipeline = DocumentPipeline(apply=args.apply)
    try:
        summary = pipeline.run()
    finally:
        pipeline.close()
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
