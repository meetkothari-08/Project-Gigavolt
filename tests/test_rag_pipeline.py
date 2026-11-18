from datetime import date
from decimal import Decimal

import pytest

from gigavolt.rag.pipeline import (
    GigavoltRAGPipeline,
    compact_telemetry,
    deduplicate_records,
    extract_equipment_identifier,
    serialize,
)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Service history for eq-5508?", "EQ-5508"),
        ("Telemetry for SN-X7-0094 last week", "SN-X7-0094"),
        ("What are common X-7000 failure modes?", None),
    ],
)
def test_extract_equipment_identifier(question, expected):
    assert extract_equipment_identifier(question) == expected


def test_serialize_converts_dates_and_decimals():
    value = {"d": date(2024, 1, 5), "n": Decimal("1.50"), "items": [Decimal("2")]}
    assert serialize(value) == {"d": "2024-01-05", "n": 1.5, "items": [2.0]}


def test_compact_telemetry_flattens_readings():
    record = {"_id": "x", "equipment_id": "SN-1", "telemetry": {"temperature_c": 41.2}}
    compact = compact_telemetry(record)
    assert compact["temperature_c"] == 41.2
    assert compact["flagged_components"] == []


def test_deduplicate_keeps_highest_priority_route():
    records = [
        {"source_id": "telemetry:1", "type": "telemetry", "record": {"_id": "1"}},
        {"source_id": "telemetry:1", "type": "high_temperature_telemetry", "record": {"_id": "1"}},
    ]
    result = deduplicate_records(records)
    assert len(result) == 1
    assert result[0]["type"] == "high_temperature_telemetry"


class FakeVector:
    def search(self, question, limit=5):
        return {
            "ids": [["doc-c0001", "doc-c0002"]],
            "documents": [["Thermal runaway procedure.", "Firmware SOP."]],
            "metadatas": [[{"source_filename": "a.pdf"}, {"source_filename": "b.pdf"}]],
        }


class FakeMariaDB:
    def __init__(self):
        self.closed = False

    def get_equipment(self, equipment_id):
        return {"equipment_id": equipment_id, "serial_number": "SN-X7-0094",
                "install_date": date(2023, 1, 1)}

    def search_table(self, table, term, limit=1):
        return [{"equipment_id": "EQ-1"}]

    def get_equipment_history(self, equipment_id, limit=3):
        return [{"dispatch_id": "D-1", "labor_cost": Decimal("120.00")}]

    def get_warranty_claims(self, equipment_id, limit=3):
        return [{"claim_id": "W-1"}]

    def get_cell_components(self, limit=5):
        return [{"part_id": "P-1", "part_name": "Lithium Cell"}]

    def get_parts(self, low_stock_only=False, limit=5):
        return [{"part_id": "P-2", "part_name": "Fuse"}]

    def close(self):
        self.closed = True


class FakeMongo:
    def __init__(self, fail=False):
        self.fail = fail
        self.closed = False

    def get_by_equipment(self, serial, limit=5):
        if self.fail:
            raise ConnectionError("mongo down")
        return [{"_id": "t1", "equipment_id": serial, "telemetry": {"temperature_c": 30}}]

    def get_fault_records(self, equipment_id=None, limit=5):
        return [{"_id": "t2", "equipment_id": equipment_id, "fault_code": "ERR_THM_204"}]

    def get_by_model(self, model, limit=5):
        return [{"_id": "t3", "model": model}]

    def get_high_temperature_records(self, model, min_temperature=40.0, limit=5):
        return [{"_id": "t3", "model": model, "telemetry": {"temperature_c": 48}}]

    def close(self):
        self.closed = True


class FakeGenerator:
    def generate(self, question, context):
        return {"answer": "Fan replaced [dispatch:D-1].", "model": "fake",
                "generation_seconds": 0.01}


def make_pipeline(mongo=None):
    return GigavoltRAGPipeline(
        vector=FakeVector(), mariadb=FakeMariaDB(), mongodb=mongo or FakeMongo(),
        generator=FakeGenerator(),
    )


def test_equipment_question_routes_to_all_three_stores():
    context = make_pipeline().retrieve("Service history for EQ-5508")
    assert [d["source_id"] for d in context["documents"]] == ["doc-c0001", "doc-c0002"]
    ids = {item["source_id"] for item in context["mariadb"]}
    assert {"equipment:EQ-5508", "dispatch:D-1", "warranty:W-1"} <= ids
    assert {item["source_id"] for item in context["mongodb"]} == {"telemetry:t1", "fault:t2"}
    assert context["errors"] == []


def test_keyword_routes_add_parts_and_model_telemetry():
    context = make_pipeline().retrieve("Which X-7000 lithium cell parts are low in stock?")
    ids = {item["source_id"] for item in context["mariadb"]}
    assert {"part:P-1", "part:P-2"} <= ids
    # Model telemetry and high-temperature telemetry are the same document;
    # the high-temperature route wins deduplication.
    assert [item["type"] for item in context["mongodb"]] == ["high_temperature_telemetry"]


def test_store_failure_is_recorded_not_raised():
    context = make_pipeline(FakeMongo(fail=True)).retrieve("Telemetry for EQ-1")
    assert context["errors"][0]["source"] == "MongoDB equipment"
    assert context["mariadb"]  # other stores still contributed


def test_ask_returns_timing_and_provenance():
    result = make_pipeline().ask("Service history for EQ-5508")
    assert result["provenance"]["model_citations_valid"] == ["dispatch:D-1"]
    assert result["retrieval_seconds"] >= 0
    assert result["sources"]["mariadb"] >= 3


def test_close_closes_database_clients():
    pipeline = make_pipeline()
    pipeline.close()
    assert pipeline.mariadb.closed and pipeline.mongodb.closed
