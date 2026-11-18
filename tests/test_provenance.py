from gigavolt.rag.provenance import (
    FALLBACK_MARKER,
    build_source_catalog,
    extract_citations,
    split_answer,
    verify_citations,
)

CONTEXT = {
    "documents": [{"source_id": "f3159dbf5de4b71b-c0001"}],
    "mariadb": [{"source_id": "dispatch:D-1", "type": "maintenance_history"}],
    "mongodb": [{"source_id": "telemetry:abc123", "type": "telemetry"}],
}


def test_catalog_maps_ids_to_databases():
    catalog = build_source_catalog(CONTEXT)
    assert catalog["f3159dbf5de4b71b-c0001"]["database"] == "ChromaDB"
    assert catalog["dispatch:D-1"] == {"database": "MariaDB", "type": "maintenance_history"}
    assert catalog["telemetry:abc123"]["database"] == "MongoDB"


def test_valid_and_invalid_citations_are_separated():
    answer = "Overheating was logged [telemetry:abc123] and fixed [dispatch:D-999]."
    result = verify_citations(answer, CONTEXT)
    assert result["model_citations_valid"] == ["telemetry:abc123"]
    assert result["model_citations_invalid"] == ["dispatch:D-999"]
    assert result["model_citations_present"] is True
    assert result["model_citations_all_valid"] is False


def test_comma_separated_ids_in_one_bracket_are_checked_individually():
    assert extract_citations("[telemetry:abc123, dispatch:D-1]") == {
        "telemetry:abc123", "dispatch:D-1",
    }
    result = verify_citations("Seen in [telemetry:abc123, dispatch:D-1].", CONTEXT)
    assert result["model_citations_all_valid"] is True


def test_fallback_source_list_is_not_counted_as_model_citation():
    answer = f"The model wrote no citations.\n\n{FALLBACK_MARKER} [dispatch:D-1]"
    model_text, fallback = split_answer(answer)
    assert FALLBACK_MARKER not in model_text
    assert fallback.startswith(FALLBACK_MARKER)

    result = verify_citations(answer, CONTEXT)
    assert result["fallback_used"] is True
    assert result["citations_present"] is True       # whole answer, legacy metric
    assert result["model_citations_present"] is False  # claim-level metric


def test_prose_inside_brackets_is_invalid():
    result = verify_citations("[STAGE 4: FIRST RESPONDER HANDOVER]", CONTEXT)
    assert result["model_citations_invalid"] == ["STAGE 4: FIRST RESPONDER HANDOVER"]


def test_answer_without_brackets_has_no_citations():
    result = verify_citations("No evidence available.", CONTEXT)
    assert result["citations_present"] is False
    assert result["all_citations_valid"] is False
