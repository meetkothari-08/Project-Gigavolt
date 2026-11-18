"""SQLite-backed processing state for the relational ingestion pipeline.

``processed_records`` stores a SHA-256 hash per (table, primary key) so a
re-run can tell NEW, MODIFIED and unchanged rows apart. ``checkpoints`` stores
the highest Audit_Logs ID already handled.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from gigavolt.config import get_settings


class RelationalState:
    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = get_settings().paths.state_dir / "relational_state.db"
        db_path = Path(db_path) if str(db_path) != ":memory:" else db_path
        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(db_path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS processed_records (
                    table_name   TEXT NOT NULL,
                    record_id    TEXT NOT NULL,
                    record_hash  TEXT NOT NULL,
                    status       TEXT NOT NULL,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (table_name, record_id)
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_name   TEXT PRIMARY KEY,
                    last_processed_id INTEGER NOT NULL DEFAULT 0,
                    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def get_record_hash(self, table_name: str, record_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT record_hash FROM processed_records WHERE table_name = ? AND record_id = ?",
            (table_name, str(record_id)),
        ).fetchone()
        return row["record_hash"] if row else None

    def save_record(self, table_name: str, record_id: str, record_hash: str) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO processed_records (table_name, record_id, record_hash, status)
                VALUES (?, ?, ?, 'processed')
                ON CONFLICT(table_name, record_id) DO UPDATE SET
                    record_hash  = excluded.record_hash,
                    status       = 'processed',
                    processed_at = CURRENT_TIMESTAMP
                """,
                (table_name, str(record_id), record_hash),
            )

    def get_checkpoint(self, name: str) -> int:
        row = self.connection.execute(
            "SELECT last_processed_id FROM checkpoints WHERE checkpoint_name = ?",
            (name,),
        ).fetchone()
        return row["last_processed_id"] if row else 0

    def save_checkpoint(self, name: str, audit_id: int) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO checkpoints (checkpoint_name, last_processed_id)
                VALUES (?, ?)
                ON CONFLICT(checkpoint_name) DO UPDATE SET
                    last_processed_id = excluded.last_processed_id,
                    updated_at        = CURRENT_TIMESTAMP
                """,
                (name, audit_id),
            )

    def close(self) -> None:
        self.connection.close()
