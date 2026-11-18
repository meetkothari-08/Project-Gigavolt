"""Hybrid RAG pipeline: route a question to MariaDB, MongoDB and ChromaDB,
assemble the evidence, generate a cited answer and validate its citations."""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from decimal import Decimal

from gigavolt.rag.generator import AnswerGenerator
from gigavolt.rag.provenance import verify_citations

EQUIPMENT_ID_PATTERNS = (
    re.compile(r"\bSN-[A-Za-z0-9-]+\b", re.IGNORECASE),  # serial number, e.g. SN-X7-0094
    re.compile(r"\bEQ-[A-Za-z0-9-]+\b", re.IGNORECASE),  # equipment ID, e.g. EQ-5508
)

SUPPLY_CHAIN_KEYWORDS = ("supplier", "lithium", "cell")
INVENTORY_KEYWORDS = ("part", "stock", "inventory", "reorder")

# Higher number wins when the same telemetry document is retrieved by
# more than one route.
TELEMETRY_PRIORITY = {
    "high_temperature_telemetry": 4,
    "fault_record": 3,
    "model_telemetry": 2,
    "telemetry": 1,
}

MAX_TELEMETRY_RECORDS = 3
DOCUMENT_CONTENT_CHARS = 500


def serialize(value):
    """Recursively convert dates and Decimals into JSON-friendly values."""
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def extract_equipment_identifier(question: str) -> str | None:
    """Return the first serial number (SN-...) or equipment ID (EQ-...) in the question."""
    for pattern in EQUIPMENT_ID_PATTERNS:
        match = pattern.search(question)
        if match:
            return match.group(0).upper()
    return None


def compact_telemetry(record: dict) -> dict:
    """Keep the diagnostic fields of a telemetry document, flattened for the prompt."""
    telemetry = record.get("telemetry") or {}
    return {
        "_id": str(record.get("_id", "")),
        "log_id": record.get("log_id"),
        "timestamp": record.get("timestamp"),
        "equipment_id": record.get("equipment_id"),
        "model": record.get("model"),
        "status": record.get("status"),
        "fault_code": record.get("fault_code"),
        "severity": record.get("severity"),
        "temperature_c": telemetry.get("temperature_c"),
        "voltage_v": telemetry.get("voltage_v"),
        "current_a": telemetry.get("current_a"),
        "soc_percent": telemetry.get("soc_percent"),
        "voltage_delta_mv": telemetry.get("voltage_delta_mv"),
        "flagged_components": record.get("flagged_components", []),
        "notes": record.get("notes", ""),
    }


def deduplicate_records(records: list[dict]) -> list[dict]:
    """Drop repeated records, keeping the copy retrieved by the highest-priority route."""
    unique: dict[str, dict] = {}
    for item in records:
        record = item.get("record", {})
        key = str(record.get("_id") or item.get("source_id") or record)
        existing = unique.get(key)
        if existing is None or (
            TELEMETRY_PRIORITY.get(item.get("type"), 0)
            > TELEMETRY_PRIORITY.get(existing.get("type"), 0)
        ):
            unique[key] = item
    return list(unique.values())


def telemetry_sort_key(item: dict) -> tuple[bool, bool, bool]:
    return (
        item["type"] == "high_temperature_telemetry",
        item["type"] == "fault_record",
        item["type"] == "model_telemetry",
    )


class GigavoltRAGPipeline:
    """Hybrid RAG pipeline using MariaDB, MongoDB and ChromaDB.

    Retrievers can be injected (useful for tests); by default they are built
    from environment configuration.
    """

    def __init__(self, vector=None, mariadb=None, mongodb=None, generator=None):
        if vector is None:
            from gigavolt.retrieval.vector import VectorRetriever
            vector = VectorRetriever()
        if mariadb is None:
            from gigavolt.retrieval.mariadb import MariaDBRetriever
            mariadb = MariaDBRetriever()
        if mongodb is None:
            from gigavolt.retrieval.mongodb import MongoDBRetriever
            mongodb = MongoDBRetriever()

        self.vector = vector
        self.mariadb = mariadb
        self.mongodb = mongodb
        self.generator = generator or AnswerGenerator()

    # ------------------------------------------------------------------
    # Retrieval routes. Each route appends to context and records its own
    # errors, so one unavailable store degrades the answer instead of
    # failing the request.
    # ------------------------------------------------------------------

    def _retrieve_documents(self, question: str, limit: int, context: dict) -> None:
        try:
            results = self.vector.search(question, limit=min(limit, 3))
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            ids = results.get("ids", [[]])[0]

            for i, document in enumerate(documents[:3]):
                metadata = metadatas[i] if i < len(metadatas) else {}
                source_id = ids[i] if i < len(ids) else f"document_{i}"
                context["documents"].append({
                    "source_id": str(source_id),
                    "content": str(document)[:DOCUMENT_CONTENT_CHARS],
                    "metadata": serialize(metadata or {}),
                })
        except Exception as exc:  # noqa: BLE001 - recorded, not raised
            context["errors"].append({"source": "ChromaDB", "error": str(exc)})

    def _retrieve_equipment(self, identifier: str, context: dict) -> dict | None:
        equipment = None
        try:
            if identifier.startswith("SN-"):
                matches = self.mariadb.search_table("equipment", identifier, limit=1)
                if matches:
                    equipment = self.mariadb.get_equipment(matches[0]["equipment_id"])
            else:
                equipment = self.mariadb.get_equipment(identifier)

            if not equipment:
                return None

            equipment = serialize(equipment)
            equipment_id = equipment["equipment_id"]
            context["mariadb"].append({
                "source_id": f"equipment:{equipment_id}",
                "type": "equipment_details",
                "record": equipment,
            })

            for record in self.mariadb.get_equipment_history(equipment_id, limit=3):
                context["mariadb"].append({
                    "source_id": f"dispatch:{record['dispatch_id']}",
                    "type": "maintenance_history",
                    "record": serialize(record),
                })

            for record in self.mariadb.get_warranty_claims(equipment_id, limit=3):
                context["mariadb"].append({
                    "source_id": f"warranty:{record['claim_id']}",
                    "type": "warranty_claim",
                    "record": serialize(record),
                })
        except Exception as exc:  # noqa: BLE001
            context["errors"].append({"source": "MariaDB equipment", "error": str(exc)})
        return equipment

    def _append_telemetry(self, records: list[dict], kind: str, prefix: str, context: dict) -> None:
        for record in records:
            context["mongodb"].append({
                "source_id": f"{prefix}:{record.get('_id', 'unknown')}",
                "type": kind,
                "record": compact_telemetry(record),
            })

    def _retrieve_unit_telemetry(self, serial: str, context: dict) -> None:
        try:
            self._append_telemetry(
                self.mongodb.get_by_equipment(serial, limit=5), "telemetry", "telemetry", context
            )
            self._append_telemetry(
                self.mongodb.get_fault_records(equipment_id=serial, limit=5),
                "fault_record", "fault", context,
            )
        except Exception as exc:  # noqa: BLE001
            context["errors"].append({"source": "MongoDB equipment", "error": str(exc)})

    def _retrieve_model_telemetry(self, model: str, context: dict) -> None:
        try:
            self._append_telemetry(
                self.mongodb.get_by_model(model, limit=5), "model_telemetry", "telemetry", context
            )
            self._append_telemetry(
                self.mongodb.get_high_temperature_records(model, min_temperature=40.0, limit=5),
                "high_temperature_telemetry", "telemetry", context,
            )
        except Exception as exc:  # noqa: BLE001
            context["errors"].append({"source": "MongoDB model telemetry", "error": str(exc)})

    def _retrieve_parts(self, records: list[dict], kind: str, context: dict) -> None:
        for record in records:
            context["mariadb"].append({
                "source_id": f"part:{record['part_id']}",
                "type": kind,
                "record": serialize(record),
            })

    def retrieve(self, question: str, limit: int = 3) -> dict:
        context: dict = {"documents": [], "mariadb": [], "mongodb": [], "errors": []}
        identifier = extract_equipment_identifier(question)
        question_lower = question.lower()

        # 1. ChromaDB: semantically closest technical document chunks.
        self._retrieve_documents(question, limit, context)

        # 2. MariaDB: equipment, maintenance history and warranty claims.
        equipment = self._retrieve_equipment(identifier, context) if identifier else None

        # 3. MongoDB: telemetry for the unit's serial number.
        serial = equipment.get("serial_number", identifier) if equipment else identifier
        if serial:
            self._retrieve_unit_telemetry(serial, context)

        # 4. MongoDB: model-level diagnostics.
        if "x-7000" in question_lower:
            self._retrieve_model_telemetry("X-7000", context)

        # 5. MariaDB: lithium-cell components and suppliers.
        if any(word in question_lower for word in SUPPLY_CHAIN_KEYWORDS):
            try:
                self._retrieve_parts(
                    self.mariadb.get_cell_components(limit=5), "supplier_component", context
                )
            except Exception as exc:  # noqa: BLE001
                context["errors"].append({"source": "MariaDB supplier lookup", "error": str(exc)})

        # 6. MariaDB: low-stock inventory.
        if any(word in question_lower for word in INVENTORY_KEYWORDS):
            try:
                self._retrieve_parts(
                    self.mariadb.get_parts(low_stock_only=True, limit=5), "low_stock_part", context
                )
            except Exception as exc:  # noqa: BLE001
                context["errors"].append({"source": "MariaDB inventory", "error": str(exc)})

        # 7. Deduplicate, prioritise diagnostic telemetry, cap prompt size.
        for source in ("documents", "mariadb", "mongodb"):
            context[source] = deduplicate_records(context[source])

        context["mongodb"].sort(key=telemetry_sort_key, reverse=True)
        context["mongodb"] = context["mongodb"][:MAX_TELEMETRY_RECORDS]
        return context

    def ask(self, question: str, limit: int = 3) -> dict:
        start = time.perf_counter()

        retrieval_start = time.perf_counter()
        context = self.retrieve(question, limit)
        retrieval_seconds = time.perf_counter() - retrieval_start

        result = self.generator.generate(question, context)
        answer = result["answer"]
        provenance = verify_citations(answer, context)

        return {
            "question": question,
            "answer": answer,
            "model": result["model"],
            "retrieval_seconds": round(retrieval_seconds, 4),
            "generation_seconds": result.get("generation_seconds"),
            "latency_seconds": round(time.perf_counter() - start, 2),
            "sources": {key: len(context[key]) for key in ("documents", "mariadb", "mongodb")},
            "provenance": provenance,
            "errors": context["errors"],
            "retrieved_context": context,
        }

    def close(self) -> None:
        self.mariadb.close()
        self.mongodb.close()
