"""Detect new and modified Silver records by comparing row hashes with saved state."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

import pymysql
import pymysql.cursors

from gigavolt.config import MariaDBSettings, get_settings
from gigavolt.ingestion.relational.state import RelationalState

FETCH_BATCH_SIZE = 500
AUDIT_CHECKPOINT = "dispatch_audit"


def serialize_value(value):
    """Convert database values into deterministic JSON values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def calculate_hash(record: dict) -> str:
    """SHA-256 of a record's canonical JSON form (sorted keys, no whitespace)."""
    normalized = {key: serialize_value(value) for key, value in record.items()}
    serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class RelationalDetector:
    """Classify rows in the six Silver tables as NEW or MODIFIED.

    Unchanged rows are skipped. Detection never writes state; the pipeline
    saves a record's hash only after the record validates and is processed.
    New dispatch audit events are read after the saved audit-ID checkpoint.
    """

    TABLE_KEYS = {
        "customers": "customer_id",
        "equipment": "equipment_id",
        "equipment_models": "model",
        "dispatches": "dispatch_id",
        "parts": "part_id",
        "warranty_claims": "claim_id",
    }

    def __init__(self, state: RelationalState | None = None, connection=None,
                 settings: MariaDBSettings | None = None):
        self.state = state or RelationalState()
        self.owns_state = state is None
        self.scanned: dict[str, int] = {}

        if connection is None:
            settings = settings or get_settings().mariadb
            connection = pymysql.connect(
                host=settings.host,
                port=settings.port,
                user=settings.user,
                password=settings.password,
                database=settings.database,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=5,
                read_timeout=30,
                write_timeout=30,
            )
        self.connection = connection

    # Kept for backwards compatibility with callers that used the class methods.
    serialize_value = staticmethod(serialize_value)
    calculate_hash = staticmethod(calculate_hash)

    def detect_table_changes(self, table_name: str) -> list[dict]:
        """Return the NEW or MODIFIED rows of one table."""
        if table_name not in self.TABLE_KEYS:
            raise ValueError("Table is not approved for detection")

        primary_key = self.TABLE_KEYS[table_name]
        changes: list[dict] = []
        scanned = 0

        with self.connection.cursor() as cursor:
            # Table name comes from the allow-list above.
            cursor.execute(f"SELECT * FROM `{table_name}`")
            while rows := cursor.fetchmany(FETCH_BATCH_SIZE):
                for record in rows:
                    record_id = record.get(primary_key)
                    if record_id is None:
                        continue
                    scanned += 1

                    current_hash = calculate_hash(record)
                    previous_hash = self.state.get_record_hash(table_name, str(record_id))

                    if previous_hash is None:
                        change_type = "NEW"
                    elif previous_hash != current_hash:
                        change_type = "MODIFIED"
                    else:
                        continue

                    changes.append({
                        "table_name": table_name,
                        "record_id": str(record_id),
                        "change_type": change_type,
                        "record_hash": current_hash,
                        "record": record,
                    })

        self.scanned[table_name] = scanned
        return changes

    def detect_all_changes(self) -> dict[str, list[dict]]:
        return {table: self.detect_table_changes(table) for table in self.TABLE_KEYS}

    def get_new_dispatch_audit_events(self) -> list[dict]:
        """Dispatch audit events after the checkpoint. Does not advance it."""
        last_id = self.state.get_checkpoint(AUDIT_CHECKPOINT)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT audit_id, audit_timestamp, table_name, operation_type,
                       old_values, new_values, change_description
                FROM Audit_Logs
                WHERE audit_id > %s
                  AND table_name = 'dispatches'
                ORDER BY audit_id ASC
                """,
                (last_id,),
            )
            return list(cursor.fetchall())

    def close(self) -> None:
        self.connection.close()
        if self.owns_state:
            self.state.close()
