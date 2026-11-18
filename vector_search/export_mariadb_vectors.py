#!/usr/bin/env python3
"""Step 4 - Export chunk text, metadata and embeddings from MariaDB Vector to JSONL,
so the vectors can be loaded into ChromaDB without re-embedding.

    python vector_search/export_mariadb_vectors.py
"""

import json

import pymysql

from _common import EXPORT_FILE as OUTPUT_FILE
from _common import vector_db_config

SQL = """
SELECT
    chunk_id,
    source_id,
    source_filename,
    source_path,
    page_number,
    chunk_index_on_page,
    token_count,
    chunk_text,
    VEC_ToText(embedding),
    created_at
FROM document_chunks
ORDER BY chunk_id
"""


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    connection = pymysql.connect(**vector_db_config())

    try:
        with connection.cursor() as cursor:
            cursor.execute(SQL)
            rows = cursor.fetchall()

        if not rows:
            raise RuntimeError("No document chunks found.")

        with OUTPUT_FILE.open("w", encoding="utf-8") as file:
            for row in rows:
                (
                    chunk_id,
                    source_id,
                    source_filename,
                    source_path,
                    page_number,
                    chunk_index_on_page,
                    token_count,
                    chunk_text,
                    vector_text,
                    created_at,
                ) = row

                if isinstance(vector_text, bytes):
                    vector_text = vector_text.decode("utf-8")

                vector = json.loads(vector_text)

                if len(vector) != 384:
                    raise ValueError(
                        f"{chunk_id}: expected 384 dimensions, "
                        f"got {len(vector)}"
                    )

                record = {
                    "chunk_id": chunk_id,
                    "source_id": source_id,
                    "source_filename": source_filename,
                    "source_path": source_path,
                    "page_number": page_number,
                    "chunk_index_on_page": chunk_index_on_page,
                    "token_count": token_count,
                    "chunk_text": chunk_text,
                    "embedding": vector,
                    "created_at": str(created_at),
                }

                file.write(
                    json.dumps(record, ensure_ascii=False) + "\n"
                )

        print(f"Exported {len(rows)} records.")
        print(f"Output: {OUTPUT_FILE}")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
