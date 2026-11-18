#!/usr/bin/env python3
"""Step 3 (prototype) - Embed chunks with E5 and store them in a MariaDB VECTOR(384)
column with an HNSW vector index (M=8, cosine).

This was the first vector-store prototype; the final store is ChromaDB.

    python vector_search/embed_to_mariadb.py
"""

import json
import sys
import time

import numpy as np
import pymysql
from sentence_transformers import SentenceTransformer

from _common import CHUNKS_FILE, EMBEDDING_DIM, MODEL_NAME, vector_db_config

BATCH_SIZE = 1



def load_chunks():
    if not CHUNKS_FILE.exists():
        raise FileNotFoundError(
            f"Chunks file not found: {CHUNKS_FILE}"
        )

    chunks = []

    with CHUNKS_FILE.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            record = json.loads(line)

            required = [
                "chunk_id",
                "source_id",
                "source_filename",
                "source_path",
                "page_number",
                "chunk_index_on_page",
                "token_count",
                "chunk_text",
            ]

            missing = [
                key for key in required
                if key not in record
            ]

            if missing:
                raise ValueError(
                    f"Line {line_number} is missing fields: {missing}"
                )

            if not record["chunk_text"].strip():
                continue

            chunks.append(record)

    if not chunks:
        raise RuntimeError("No valid chunks were found.")

    ids = [chunk["chunk_id"] for chunk in chunks]

    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate chunk IDs detected.")

    return chunks


def create_schema(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            chunk_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
            source_id VARCHAR(32) NOT NULL,
            source_filename VARCHAR(255) NOT NULL,
            source_path VARCHAR(768) NOT NULL,
            page_number INT UNSIGNED NOT NULL,
            chunk_index_on_page INT UNSIGNED NOT NULL,
            token_count INT UNSIGNED NOT NULL,
            chunk_text MEDIUMTEXT NOT NULL,
            embedding VECTOR(384) NOT NULL,
            created_at TIMESTAMP NOT NULL
                DEFAULT CURRENT_TIMESTAMP,
            VECTOR INDEX (embedding)
                M=8 DISTANCE=cosine
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)


def main():
    print("=" * 65)
    print("GIGAVOLT M4: DOCUMENT EMBEDDING GENERATION")
    print("=" * 65)

    chunks = load_chunks()

    print(f"Loaded {len(chunks)} chunks.")
    print(f"Embedding model: {MODEL_NAME}")
    print(f"Vector dimensions: {EMBEDDING_DIM}")

    # Check that this model configuration matches our chunks.
    print("\nLoading embedding model...")
    model = SentenceTransformer(MODEL_NAME, device="cpu")

    dimension = model.get_sentence_embedding_dimension()

    if dimension != EMBEDDING_DIM:
        raise RuntimeError(
            f"Expected {EMBEDDING_DIM} dimensions, "
            f"but model returned {dimension}."
        )

    # E5 uses the passage prefix for stored document text.
    passages = [
        "passage: " + chunk["chunk_text"]
        for chunk in chunks
    ]

    print(f"\nGenerating embeddings in batches of {BATCH_SIZE}...")
    start = time.perf_counter()

    embeddings = model.encode(
        passages,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    embedding_time = time.perf_counter() - start

    if embeddings.shape != (len(chunks), EMBEDDING_DIM):
        raise RuntimeError(
            f"Unexpected embedding shape: {embeddings.shape}"
        )

    if not np.isfinite(embeddings).all():
        raise RuntimeError("Embeddings contain invalid numeric values.")

    norms = np.linalg.norm(embeddings, axis=1)

    if not np.allclose(norms, 1.0, atol=1e-3):
        raise RuntimeError("Some embeddings are not normalized.")

    print(f"Embedding shape: {embeddings.shape}")
    print(f"Embedding generation time: {embedding_time:.2f} seconds")

    print("\nConnecting to MariaDB...")
    connection = pymysql.connect(**vector_db_config(), autocommit=False)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            print(f"MariaDB version: {cursor.fetchone()[0]}")

            create_schema(cursor)
            connection.commit()

            # Rebuild only our dedicated M4 document-chunk dataset.
            # Other databases and tables are not deleted.
            print("\nClearing previous M4 document_chunks rows...")
            cursor.execute("DELETE FROM document_chunks")
            connection.commit()

            sql = """
                INSERT INTO document_chunks (
                    chunk_id,
                    source_id,
                    source_filename,
                    source_path,
                    page_number,
                    chunk_index_on_page,
                    token_count,
                    chunk_text,
                    embedding
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    VEC_FromText(%s)
                )
            """

            rows = []

            for chunk, vector in zip(chunks, embeddings):
                vector_text = json.dumps(
                    [float(value) for value in vector],
                    separators=(",", ":"),
                )

                rows.append((
                    chunk["chunk_id"],
                    chunk["source_id"],
                    chunk["source_filename"],
                    chunk["source_path"],
                    int(chunk["page_number"]),
                    int(chunk["chunk_index_on_page"]),
                    int(chunk["token_count"]),
                    chunk["chunk_text"],
                    vector_text,
                ))

            print(f"Inserting {len(rows)} chunks and vectors...")
            insert_start = time.perf_counter()

            for offset in range(0, len(rows), BATCH_SIZE):
                batch = rows[offset:offset + BATCH_SIZE]
                cursor.executemany(sql, batch)
                connection.commit()

                print(
                    f"Stored {min(offset + len(batch), len(rows))}"
                    f" / {len(rows)} chunks"
                )

            insert_time = time.perf_counter() - insert_start

            cursor.execute("""
                SELECT
                    COUNT(*),
                    COUNT(embedding),
                    MIN(token_count),
                    MAX(token_count)
                FROM document_chunks
            """)

            count, embedded_count, min_tokens, max_tokens = (
                cursor.fetchone()
            )

            print("\n" + "=" * 65)
            print("EMBEDDING PIPELINE COMPLETE")
            print("=" * 65)
            print(f"Source chunks:        {len(chunks)}")
            print(f"Rows stored:          {count}")
            print(f"Rows with embeddings: {embedded_count}")
            print(f"Smallest chunk:       {min_tokens} tokens")
            print(f"Largest chunk:        {max_tokens} tokens")
            print(f"Embedding time:       {embedding_time:.2f} seconds")
            print(f"Database insert time: {insert_time:.2f} seconds")
            print("Vector index:         M=8, cosine distance")

            if count != len(chunks) or embedded_count != len(chunks):
                raise RuntimeError(
                    "Stored row counts do not match input chunks."
                )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
