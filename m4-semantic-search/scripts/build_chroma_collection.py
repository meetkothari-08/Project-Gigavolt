#!/usr/bin/env python3
"""Step 5 - Create the final persistent ChromaDB collection from the exported vectors.

Uses the HNSW settings selected by tune_hnsw.py (cosine, M=8,
ef_construction=50, ef_search=20) and verifies count, IDs and dimensions.
Refuses to overwrite an existing collection.

    python m4-semantic-search/scripts/build_chroma_collection.py
"""

import sys

import chromadb

from _common import (
    CHROMA_DIR,
    CHUNKS_FILE,
    EXPORT_FILE,
    FINAL_HNSW,
    MODEL_NAME,
    read_jsonl,
)
from _common import FINAL_COLLECTION as COLLECTION_NAME

BATCH_SIZE = 10


def main():
    exported = read_jsonl(EXPORT_FILE)
    chunks = read_jsonl(CHUNKS_FILE)

    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    export_ids = [row["chunk_id"] for row in exported]

    if len(export_ids) != 64 or len(set(export_ids)) != 64:
        raise ValueError("Expected 64 unique exported vectors.")

    if set(export_ids) != set(chunks_by_id):
        raise ValueError(
            "The vector export and current chunk file do not match."
        )

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    if COLLECTION_NAME in client.list_collections():
        raise RuntimeError(
            f"{COLLECTION_NAME} already exists. "
            "No existing collection was changed. Use a new name "
            "or inspect the existing collection first."
        )

    # Make the graph searchable before reaching the default 100-vector
    # brute-force buffer threshold. Construction settings are immutable
    # for this collection and reflect our best observed test result.
    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=None,
        metadata={
            "description": "Final Milestone 4 technical document collection",
            "embedding_model": MODEL_NAME,
            "embedding_dimensions": 384,
            "tuning_basis": "64 chunks; 8 distinct queries; initial benchmark",
        },
        configuration={"hnsw": FINAL_HNSW},
    )

    for start in range(0, len(exported), BATCH_SIZE):
        batch = exported[start:start + BATCH_SIZE]

        ids = []
        documents = []
        embeddings = []
        metadatas = []

        for row in batch:
            chunk = chunks_by_id[row["chunk_id"]]
            vector = [float(value) for value in row["embedding"]]

            if len(vector) != 384:
                raise ValueError(
                    f"{row['chunk_id']}: vector is not 384-dimensional."
                )

            if row["chunk_text"] != chunk["chunk_text"]:
                raise ValueError(
                    f"{row['chunk_id']}: text mismatch in export."
                )

            ids.append(row["chunk_id"])
            documents.append(row["chunk_text"])
            embeddings.append(vector)

            metadatas.append({
                "source_id": str(row["source_id"]),
                "source_filename": str(row["source_filename"]),
                "source_path": str(row["source_path"]),
                "page_number": int(row["page_number"]),
                "page_start": int(chunk["page_start"]),
                "page_end": int(chunk["page_end"]),
                "chunk_index": int(chunk["chunk_index"]),
                "chunk_index_on_page": int(
                    row["chunk_index_on_page"]
                ),
                "token_count": int(row["token_count"]),
                "token_start": int(chunk["token_start"]),
                "token_end": int(chunk["token_end"]),
                "overlap_tokens_with_previous": int(
                    chunk["overlap_tokens_with_previous"]
                ),
                "created_at": str(row["created_at"]),
                "embedding_model": MODEL_NAME,
            })

        collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        print(
            f"Imported {min(start + len(batch), len(exported))}"
            f" / {len(exported)}"
        )

    # Verify the persistent collection.
    stored = collection.get(
        ids=export_ids,
        include=["documents", "embeddings", "metadatas"],
    )

    if collection.count() != 64:
        raise RuntimeError("Final collection count is not 64.")

    if set(stored["ids"]) != set(export_ids):
        raise RuntimeError("Final collection IDs don't match the export.")

    if len(stored["embeddings"]) != 64 or any(
        len(vector) != 384 for vector in stored["embeddings"]
    ):
        raise RuntimeError("Embedding verification failed.")

    print("\nFINAL COLLECTION CREATED AND VERIFIED")
    print(f"Collection: {collection.name}")
    print(f"Records: {collection.count()}")
    print("Embedding dimensions: 384")
    print(f"Configuration: {collection.configuration}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
