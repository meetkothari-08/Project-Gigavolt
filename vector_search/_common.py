"""Shared paths, settings and query sets for the offline vector-search scripts.

Paths follow ``gigavolt.config`` (override with GIGAVOLT_DATA_DIR,
GIGAVOLT_DOCUMENTS_DIR, GIGAVOLT_PROCESSED_DIR, GIGAVOLT_CHROMA_DIR).

The MariaDB Vector prototype database is configured with VECTOR_DB_HOST,
VECTOR_DB_PORT, VECTOR_DB_USER, VECTOR_DB_PASSWORD and VECTOR_DB_DATABASE.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running the scripts directly from a checkout without `pip install -e .`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gigavolt.config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, get_settings  # noqa: E402

_paths = get_settings().paths

DOCUMENTS_DIR = _paths.documents_dir
PROCESSED_DIR = _paths.processed_dir
CHROMA_DIR = _paths.chroma_dir

CHUNKS_FILE = PROCESSED_DIR / "chunks.jsonl"
PAGES_FILE = PROCESSED_DIR / "extracted_pages.jsonl"
SUMMARY_FILE = PROCESSED_DIR / "summary.json"
EXPORT_FILE = PROCESSED_DIR / "mariadb_vectors_export.jsonl"

MODEL_NAME = EMBEDDING_MODEL
EMBEDDING_DIM = EMBEDDING_DIMENSIONS
FINAL_COLLECTION = get_settings().vector.collection

# Eight distinct queries used for HNSW tuning and the ChromaDB latency benchmark.
BENCHMARK_QUERIES = [
    "What caused the X-7000 contactor flashover?",
    "What corrective actions prevent pre-charge contactor failure?",
    "What are the emergency procedures for thermal runaway?",
    "How should technicians perform firmware flashing?",
    "What are the procedures for X-7000 site acceptance testing?",
    "What causes low isolation trips in battery equipment?",
    "What are the battery cell temperature and voltage specifications?",
    "What corrective actions address chiller relief valve problems?",
]

# Chroma HNSW settings chosen from the tuning experiment
# (results: benchmarks/results/vector/chroma_hnsw_tuning.csv).
FINAL_HNSW = {
    "space": "cosine",
    "max_neighbors": 8,
    "ef_construction": 50,
    "ef_search": 20,
    "batch_size": 10,
    "sync_threshold": 100,
    "num_threads": 1,
}


def vector_db_config() -> dict:
    """Connection settings for the MariaDB Vector prototype database."""
    password = os.getenv("VECTOR_DB_PASSWORD")
    if not password:
        raise RuntimeError("Set VECTOR_DB_PASSWORD (and VECTOR_DB_USER) in the environment.")
    return {
        "host": os.getenv("VECTOR_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("VECTOR_DB_PORT", "3306")),
        "user": os.getenv("VECTOR_DB_USER", "gigavolt_vector"),
        "password": password,
        "database": os.getenv("VECTOR_DB_DATABASE", "gigavolt_vector_lab"),
        "connect_timeout": 15,
        "charset": "utf8mb4",
    }


def read_jsonl(path: Path) -> list[dict]:
    import json

    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
