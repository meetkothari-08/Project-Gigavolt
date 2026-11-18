import copy
from datetime import date
from decimal import Decimal

from gigavolt.ingestion.relational.detector import RelationalDetector, calculate_hash
from gigavolt.ingestion.relational.pipeline import RelationalPipeline
from gigavolt.ingestion.relational.state import RelationalState
from gigavolt.ingestion.relational.validator import RelationalValidator


def test_hash_is_order_independent_and_type_stable():
    a = {"id": "EQ-1", "installed": date(2024, 1, 1), "cost": Decimal("1.50")}
    b = {"cost": Decimal("1.50"), "installed": date(2024, 1, 1), "id": "EQ-1"}
    assert calculate_hash(a) == calculate_hash(b)
    assert calculate_hash(a) != calculate_hash({**a, "cost": Decimal("1.51")})


def test_validator_accepts_clean_records(silver_tables):
    validator = RelationalValidator()
    for table, rows in silver_tables.items():
        assert validator.validate(table, rows[0]) == {"valid": True, "errors": []}


def test_validator_rejects_bad_records():
    validator = RelationalValidator()
    result = validator.validate("warranty_claims", {
        "claim_id": "W-1", "equipment_id": "", "claim_date": "03/04/2024",
        "claim_amount": "100", "approved_amount": "250",
    })
    assert not result["valid"]
    assert "Missing required field: equipment_id" in result["errors"]
    assert "Invalid date value: claim_date" in result["errors"]
    assert "Approved amount exceeds claim amount" in result["errors"]

    parts = validator.validate("parts", {"part_id": "P", "part_name": "Fuse",
                                         "stock_quantity": -1, "unit_cost": "$4"})
    assert "Stock quantity cannot be negative" in parts["errors"]
    assert "Invalid numeric value: unit_cost" in parts["errors"]
    assert validator.validate("users", {})["errors"] == ["Unapproved table"]


def run(tables, state, audit=None, connection_factory=None, dry_run=False):
    detector = RelationalDetector(state=state, connection=connection_factory(tables, audit))
    return RelationalPipeline(detector=detector).run(dry_run=dry_run)


def test_pipeline_detects_new_then_unchanged_then_modified(silver_tables,
                                                           fake_connection_factory):
    state = RelationalState(":memory:")
    audit = [{"audit_id": 1, "operation_type": "INSERT",
              "change_description": "New dispatch record created: D-1"}]

    dry = run(silver_tables, state, audit, fake_connection_factory, dry_run=True)
    assert dry["new"] == 6 and dry["processed"] == 0
    assert state.get_checkpoint("dispatch_audit") == 0  # dry run writes nothing

    first = run(silver_tables, state, audit, fake_connection_factory)
    assert first == {"new": 6, "modified": 0, "unchanged": 0, "processed": 6,
                     "invalid": 0, "failed": 0, "audit_events": 1}
    assert state.get_checkpoint("dispatch_audit") == 1

    second = run(silver_tables, state, audit, fake_connection_factory)
    assert second["unchanged"] == 6 and second["new"] == second["modified"] == 0
    assert second["audit_events"] == 0  # checkpoint advanced past event 1

    changed = copy.deepcopy(silver_tables)
    changed["equipment"][0]["model"] = "X-9000"
    third = run(changed, state, audit, fake_connection_factory)
    assert third["modified"] == 1 and third["processed"] == 1 and third["unchanged"] == 5

    # Restoring the original value is itself a modification (hash differs again).
    fourth = run(silver_tables, state, audit, fake_connection_factory)
    assert fourth["modified"] == 1


def test_invalid_records_are_not_marked_processed(silver_tables, fake_connection_factory):
    state = RelationalState(":memory:")
    bad = copy.deepcopy(silver_tables)
    bad["parts"][0]["stock_quantity"] = -5

    summary = run(bad, state, connection_factory=fake_connection_factory)
    assert summary["invalid"] == 1
    assert state.get_record_hash("parts", "P-1") is None  # retried on the next run
