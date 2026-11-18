"""Integration tests against a real MariaDB deployed with ``scripts/deploy_database.sh``.

Skipped unless GIGAVOLT_TEST_MARIADB=1. Uses the MARIADB_* connection settings.

    GIGAVOLT_TEST_MARIADB=1 MARIADB_USER=root pytest tests/test_integration_mariadb.py
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("GIGAVOLT_TEST_MARIADB") != "1",
    reason="set GIGAVOLT_TEST_MARIADB=1 to run against a seeded MariaDB",
)


@pytest.fixture
def retriever():
    from gigavolt.retrieval.mariadb import MariaDBRetriever

    instance = MariaDBRetriever()
    yield instance
    instance.close()


def test_equipment_lookup_joins_customer_and_model(retriever):
    equipment = retriever.get_equipment("EQ-5508")
    assert equipment["equipment_id"] == "EQ-5508"
    assert equipment["company_name"]
    assert equipment["capacity_kw"] is not None


def test_history_claims_and_parts(retriever):
    assert isinstance(retriever.get_equipment_history("EQ-5508"), list)
    assert isinstance(retriever.get_warranty_claims("EQ-5508"), list)
    low = retriever.get_parts(low_stock_only=True, limit=5)
    assert all(row["stock_quantity"] <= row["reorder_level"] for row in low)
    assert retriever.get_cell_components(limit=5)


def test_search_table_rejects_unknown_tables(retriever):
    with pytest.raises(ValueError):
        retriever.search_table("Audit_Logs", "x")
    assert retriever.search_table("equipment", "EQ-5508", limit=1)


def test_relational_pipeline_baselines_all_silver_rows(tmp_path):
    from gigavolt.ingestion.relational.detector import RelationalDetector
    from gigavolt.ingestion.relational.pipeline import RelationalPipeline
    from gigavolt.ingestion.relational.state import RelationalState

    state = RelationalState(tmp_path / "state.db")
    first = RelationalPipeline(RelationalDetector(state=state)).run()
    assert first["new"] == 9296 and first["invalid"] == 0 and first["failed"] == 0

    state = RelationalState(tmp_path / "state.db")
    second = RelationalPipeline(RelationalDetector(state=state)).run()
    assert second["unchanged"] == 9296 and second["new"] == second["modified"] == 0
