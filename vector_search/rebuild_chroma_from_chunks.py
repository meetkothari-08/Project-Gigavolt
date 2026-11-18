#!/usr/bin/env python3
"""Alternative to steps 3-5: embed chunks.jsonl directly and build a ChromaDB
collection (`gigavolt_m4_rebuilt`), skipping the MariaDB Vector prototype.
Never touches the final collection.

    python vector_search/rebuild_chroma_from_chunks.py
"""

import chromadb
from sentence_transformers import SentenceTransformer

from _common import CHROMA_DIR, CHUNKS_FILE, FINAL_HNSW, MODEL_NAME, read_jsonl

COLLECTION_NAME = "gigavolt_m4_rebuilt"
BATCH_SIZE = 1


def main():
    chunks = read_jsonl(CHUNKS_FILE)

    if not chunks:
        raise RuntimeError("No chunks found.")

    ids = [c["chunk_id"] for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate chunk IDs found.")

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    if COLLECTION_NAME in client.list_collections():
        raise RuntimeError(
            f"{COLLECTION_NAME} already exists. "
            "Inspect it before attempting a rebuild."
        )

    print(f"Loading {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME, device="cpu")

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=None,
        metadata={"embedding_model": MODEL_NAME, "embedding_dimensions": 384},
        configuration={"hnsw": FINAL_HNSW},
    )

    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start:start + BATCH_SIZE]
        texts = [c["chunk_text"] for c in batch]

        vectors = model.encode(
            ["passage: " + t for t in texts],
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

        metadatas = []
        for c in batch:
            metadatas.append({
                "source_id": str(c["source_id"]),
                "source_filename": str(c["source_filename"]),
                "source_path": str(c["source_path"]),
                "page_start": int(c["page_start"]),
                "page_end": int(c["page_end"]),
                "chunk_index": int(c["chunk_index"]),
                "token_count": int(c["token_count"]),
                "overlap_tokens_with_previous": int(
                    c["overlap_tokens_with_previous"]
                ),
                "embedding_model": MODEL_NAME,
            })

        collection.add(
            ids=[c["chunk_id"] for c in batch],
            documents=texts,
            embeddings=vectors.tolist(),
            metadatas=metadatas,
        )

        print(f"Embedded and stored {min(start + len(batch), len(chunks))}/{len(chunks)}")

    assert collection.count() == len(chunks)
    print("\nRebuild complete.")
    print("Collection:", collection.name)
    print("Stored records:", collection.count())
    print("HNSW:", collection.configuration["hnsw"])
    print("Existing final collection was not modified.")


if __name__ == "__main__":
    main()
