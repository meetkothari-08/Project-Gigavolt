"""Benchmark helpers, citation re-audit and the raw-data profiler."""

import csv
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rag_benchmark = load("m6-ops-evaluation/benchmark/rag_benchmark.py", "rag_benchmark")
audit_saved = load("m6-ops-evaluation/benchmark/audit_saved_answers.py", "audit_saved_answers")
profiler = load("m1-erp-pipeline/tools/profile_raw_erp.py", "profile_raw_erp")


@pytest.mark.parametrize(("percent", "expected"), [(0, 1.0), (50, 2.5), (100, 4.0)])
def test_percentile_interpolates(percent, expected):
    assert rag_benchmark.percentile([4.0, 1.0, 3.0, 2.0], percent) == expected


def test_percentile_edge_cases():
    assert rag_benchmark.percentile([], 95) == 0.0
    assert rag_benchmark.percentile([7.0], 99) == 7.0


def test_audit_classifies_model_citations(tmp_path):
    path = tmp_path / "bench.csv"
    rows = [
        {"question_id": 1, "status": "success",
         "answer": "Ok [telemetry:abc, part:PRT-1].\n\nRetrieved Sources: [x]"},
        {"question_id": 2, "status": "success",
         "answer": "[STAGE 4: HANDOVER]\n\nRetrieved Sources: [x]"},
        {"question_id": 3, "status": "success", "answer": "No brackets at all."},
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    report = audit_saved.audit(path, known_chunks=None)
    assert report["answers"] == 3
    assert report["fallback_used"] == 2
    assert report["answers_with_model_source_ids"] == 1
    assert report["answers_with_non_id_brackets"] == 1
    assert report["answers_with_only_clean_model_citations"] == 1


def write_csv(directory: Path, name: str, rows: list[dict]):
    with (directory / f"{name}.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_profiler_detects_quality_issues(tmp_path):
    write_csv(tmp_path, "customers", [
        {"customer_id": "C-1", "created_date": "2023-01-02", "status": "Active"},
        {"customer_id": "C-1", "created_date": "01/02/2023", "status": "active"},
    ])
    write_csv(tmp_path, "equipment", [
        {"equipment_id": "EQ-1", "customer_id": "C-1", "install_date": "2023-01-02T00:00:00Z",
         "warranty_expiration": "2024-01-02", "capacity_kw": "500", "status": "In Service"},
    ])
    write_csv(tmp_path, "dispatches", [
        {"dispatch_id": "D-1", "equipment_id": "EQ-404", "dispatch_date": "2024-01-02",
         "hours_spent": "1", "labor_cost": "$1,200.00", "status": "Done",
         "service_type": "Repair", "technician": "  Lee  ",
         "resolution_summary": "<p>Fixed</p>"},
    ])
    write_csv(tmp_path, "parts", [
        {"part_id": "P-1", "unit_cost": "1", "unit_price": "2", "stock_quantity": "3",
         "reorder_level": "4"},
    ])
    write_csv(tmp_path, "warranty_claims", [
        {"claim_id": "W-1", "equipment_id": "EQ-1", "dispatch_id": "D-1", "part_id": "NULL",
         "claim_date": "2024-01-02", "claim_amount": "10", "approved_amount": "NULL",
         "status": "Open"},
    ])

    data = {table: profiler.read_table(tmp_path, table) for table in profiler.TABLES}
    customers = profiler.profile_table("customers", data["customers"])
    assert customers["duplicate_key_rows"] == 1
    assert customers["date_formats"]["created_date"] == {"YYYY-MM-DD": 1, "MM/DD/YYYY": 1}
    assert "active" in customers["casing_variants"]["status"]

    dispatches = profiler.profile_table("dispatches", data["dispatches"])
    assert dispatches["cells_with_html"] == 1
    assert dispatches["cells_with_padding"] == 1
    assert dispatches["non_numeric_values"]["labor_cost"]["count"] == 1

    equipment = profiler.profile_table("equipment", data["equipment"])
    assert equipment["date_formats"]["install_date"] == {"ISO-8601 timestamp": 1}

    fks = profiler.profile_foreign_keys(data)
    assert fks["dispatches.equipment_id -> equipment"]["orphaned"] == 1
    assert fks["warranty_claims.part_id -> parts"]["blank"] == 1


compare_silver = load("m1-erp-pipeline/tools/compare_silver.py", "compare_silver")


@pytest.mark.parametrize(
    ("table", "column", "value", "expected"),
    [
        ("customers", "status", "INACTIVE\r", "INACTIVE"),
        ("equipment", "location_notes", "\r", None),
        ("equipment", "location_notes", "Backup   unit  near dock\r", "Backup unit near dock"),
        ("equipment", "location_notes", "NULL\r", None),
        ("customers", "zip", "2113", "02113"),
        ("warranty_claims", "denial_reason", "N/A", None),
        ("warranty_claims", "denial_reason", "Normal wear and tear excluded",
         "Normal wear and tear excluded"),
        ("dispatches", "hours_spent", 2.5, 2.5),
    ],
)
def test_documented_production_fixes(table, column, value, expected):
    assert compare_silver.apply_production_fixes(table, column, value) == expected


def test_python_clean_text_mirrors_sql_rules():
    assert compare_silver.clean_text("<p>N/A</p>") is None
    assert compare_silver.clean_text(" <b>Volt  Corp</b> ") == "Volt Corp"
