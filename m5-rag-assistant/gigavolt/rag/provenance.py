"""Citation validation against the retrieved evidence.

Every retrieved item carries a ``source_id`` such as ``dispatch:DISP-10234``,
``telemetry:6adf887c...`` or a document chunk ID. This module checks that each
ID the model cites was actually present in the context it was given.

Two details matter for honest scoring:

* The generator appends a ``Retrieved Sources:`` list when the model cites
  nothing. That list is a transparency aid, not a model citation, so it is
  excluded from claim-level scoring (``model_citations_*`` fields).
* Models sometimes put several IDs in one bracket (``[a, b]``). Each
  comma-separated token is checked on its own.

Validation is identifier-level: a valid citation proves the source was
retrieved, not that it semantically supports the sentence it follows.
"""

from __future__ import annotations

import re

FALLBACK_MARKER = "Retrieved Sources:"

CITATION_PATTERN = re.compile(r"\[([^\[\]]+)\]")

SOURCE_GROUPS = {
    "ChromaDB": "documents",
    "MariaDB": "mariadb",
    "MongoDB": "mongodb",
}


def build_source_catalog(context: dict) -> dict[str, dict]:
    """Map every retrieved source ID to its database and record type."""
    catalog: dict[str, dict] = {}
    for database, key in SOURCE_GROUPS.items():
        for record in context.get(key, []):
            source_id = record.get("source_id")
            if source_id:
                catalog[source_id] = {
                    "database": database,
                    "type": record.get("type", "document"),
                }
    return catalog


def split_answer(answer: str) -> tuple[str, str]:
    """Split an answer into (model-written text, appended fallback source list)."""
    head, marker, tail = answer.partition(FALLBACK_MARKER)
    return head, (marker + tail) if marker else ""


def extract_citations(text: str) -> set[str]:
    """Return every bracketed token, splitting comma-separated lists."""
    tokens: set[str] = set()
    for group in CITATION_PATTERN.findall(text):
        for token in group.split(","):
            token = token.strip()
            if token:
                tokens.add(token)
    return tokens


def verify_citations(answer: str, context: dict) -> dict:
    """Score the citations in ``answer`` against the IDs present in ``context``.

    ``citations_present`` / ``all_citations_valid`` cover the full answer,
    including the fallback list. The ``model_citations_*`` fields cover only
    the text the model wrote and are the claim-level provenance metric.
    """
    catalog = build_source_catalog(context)
    model_text, fallback_text = split_answer(answer)

    model_ids = extract_citations(model_text)
    all_ids = model_ids | extract_citations(fallback_text)

    valid = sorted(all_ids & catalog.keys())
    invalid = sorted(all_ids - catalog.keys())
    model_valid = sorted(model_ids & catalog.keys())
    model_invalid = sorted(model_ids - catalog.keys())

    return {
        "available_sources": catalog,
        "cited_sources": {source_id: catalog[source_id] for source_id in valid},
        "invalid_citations": invalid,
        "citation_count": len(valid),
        "citations_present": bool(all_ids),
        "all_citations_valid": bool(all_ids) and not invalid,
        "fallback_used": bool(fallback_text),
        "model_citations_valid": model_valid,
        "model_citations_invalid": model_invalid,
        "model_citations_present": bool(model_ids),
        "model_citations_all_valid": bool(model_ids) and not model_invalid,
    }
