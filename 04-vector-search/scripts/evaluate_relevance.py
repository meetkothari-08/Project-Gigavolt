#!/usr/bin/env python3
"""Source-level retrieval evaluation: 25 questions, each labelled with the
document expected to answer it. Reports Hit@5 and MRR and writes a
candidate file for optional human relevance review (review_relevance.py).

These are source-level proxy metrics, not human relevance judgments.

    python 04-vector-search/scripts/evaluate_relevance.py
"""

import csv

import chromadb
from sentence_transformers import SentenceTransformer

from _common import CHROMA_DIR, MODEL_NAME
from _common import FINAL_COLLECTION as COLLECTION_NAME
from _common import PROCESSED_DIR as OUTPUT_DIR

TOP_K = 5

# Each query is labelled with the source document expected to answer it.
TEST_QUERIES = [
    {
        "id": "Q01",
        "query": "What problem and remedy does engineering change order GV-ECO-2024-019 address?",
        "expected_source": "GV-ECO-2024-019",
    },
    {
        "id": "Q02",
        "query": "What change was made to address the chiller relief valve issue?",
        "expected_source": "GV-ECO-2024-031",
    },
    {
        "id": "Q03",
        "query": "What corrective torque requirements are specified in the re-torque change order?",
        "expected_source": "GV-ECO-2024-044",
    },
    {
        "id": "Q04",
        "query": "What changes are required for the cabinet door seal?",
        "expected_source": "GV-ECO-2024-052",
    },
    {
        "id": "Q05",
        "query": "What happened during the G-3500 thermal incident, and what were the investigation findings?",
        "expected_source": "GV-INC-2024-088",
    },
    {
        "id": "Q06",
        "query": "What caused the X-7000 main contactor flashover, and what corrective actions were recommended?",
        "expected_source": "GV-INC-2024-104",
    },
    {
        "id": "Q07",
        "query": "What caused the low isolation trip, and what remediation was identified?",
        "expected_source": "GV-INC-2024-119",
    },
    {
        "id": "Q08",
        "query": "What operating and maintenance procedures are documented for the C-1200?",
        "expected_source": "GV-MAN-C1200-003",
    },
    {
        "id": "Q09",
        "query": "How should the G-3500 chiller and equipment be operated and maintained?",
        "expected_source": "GV-MAN-G3500-002",
    },
    {
        "id": "Q10",
        "query": "What operating instructions and safety precautions apply to the X-7000 Megapack?",
        "expected_source": "GV-MAN-X7000-001",
    },
    {
        "id": "Q11",
        "query": "How should technicians calibrate temperature and voltage measurements?",
        "expected_source": "GV-SOP-CAL-420",
    },
    {
        "id": "Q12",
        "query": "What are the site acceptance testing and commissioning steps for the X-7000?",
        "expected_source": "GV-SOP-COMM-201",
    },
    {
        "id": "Q13",
        "query": "What steps are required for end-of-life equipment decommissioning?",
        "expected_source": "GV-SOP-DECOM-601",
    },
    {
        "id": "Q14",
        "query": "What is the procedure for safely flashing or updating equipment firmware?",
        "expected_source": "GV-SOP-FIRM-105",
    },
    {
        "id": "Q15",
        "query": "How should technicians troubleshoot chiller and refrigerant system problems?",
        "expected_source": "GV-SOP-HVAC-310",
    },
    {
        "id": "Q16",
        "query": "What emergency procedures should be followed for a BESS fire or thermal runaway?",
        "expected_source": "GV-SOP-SAFETY-900",
    },
    {
        "id": "Q17",
        "query": "How should a technician submit and process a field warranty claim?",
        "expected_source": "GV-SOP-WAR-101",
    },
    {
        "id": "Q18",
        "query": "What are the main subsystems and architectural elements of the battery management system?",
        "expected_source": "GV-SPEC-BMS-ARC-01",
    },
    {
        "id": "Q19",
        "query": "What technical characteristics and operating limits are specified for the LFP battery cell?",
        "expected_source": "GV-SPEC-CELL-LFP-08",
    },
    {
        "id": "Q20",
        "query": "What technical specifications apply to the NMC-65 battery cell?",
        "expected_source": "GV-SPEC-CELL-NMC-65",
    },
    {
        "id": "Q21",
        "query": "What are the specifications and ratings of the DC pyro fuse?",
        "expected_source": "GV-SPEC-FUSE-PYRO-04",
    },
    {
        "id": "Q22",
        "query": "What properties and temperature limits apply to the glycol heat transfer material?",
        "expected_source": "GV-SPEC-THERM-GLY-02",
    },
    {
        "id": "Q23",
        "query": "What quality findings or nonconformities were identified in the supplier audit?",
        "expected_source": "GV-SUP-AUD-502",
    },
    {
        "id": "Q24",
        "query": "How are suppliers and components integrated across the supply chain?",
        "expected_source": "GV-SUP-REP-401",
    },
    {
        "id": "Q25",
        "query": "What supply chain risks and supplier dependencies are described in the risk assessment?",
        "expected_source": "GV-SUP-REP-409",
    },
]


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    candidates_file = OUTPUT_DIR / "relevance_candidates.csv"
    summary_file = OUTPUT_DIR / "relevance_summary.csv"

    print("Connecting to the final ChromaDB collection...")
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_collection(COLLECTION_NAME)

    if collection.count() != 64:
        raise RuntimeError(
            f"Expected 64 chunks, found {collection.count()}."
        )

    # Set a consistent search setting for this evaluation.
    collection.modify(
        configuration={"hnsw": {"ef_search": 20}}
    )

    print(f"Collection: {COLLECTION_NAME}")
    print(f"Records: {collection.count()}")
    print(f"Queries: {len(TEST_QUERIES)}")
    print(f"Top K: {TOP_K}")
    print("Loading query embedding model...")

    model = SentenceTransformer(MODEL_NAME, device="cpu")

    query_vectors = model.encode(
        ["query: " + item["query"] for item in TEST_QUERIES],
        batch_size=1,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )

    candidate_rows = []
    summary_rows = []

    for item, vector in zip(TEST_QUERIES, query_vectors):
        result = collection.query(
            query_embeddings=[vector.tolist()],
            n_results=TOP_K,
            include=["documents", "metadatas", "distances"],
        )

        ids = result["ids"][0]
        docs = result["documents"][0]
        metadatas = result["metadatas"][0]
        distances = result["distances"][0]

        expected = item["expected_source"].casefold()
        expected_ranks = []
        expected_matches = 0
        distinct_sources = set()

        for rank, (chunk_id, document, metadata, distance) in enumerate(
            zip(ids, docs, metadatas, distances), start=1
        ):
            filename = metadata.get("source_filename", "")
            source_match = expected in filename.casefold()

            if source_match:
                expected_ranks.append(rank)
                expected_matches += 1

            distinct_sources.add(filename)

            candidate_rows.append({
                "query_id": item["id"],
                "query": item["query"],
                "expected_source": item["expected_source"],
                "rank": rank,
                "chunk_id": chunk_id,
                "source_filename": filename,
                "page_start": metadata.get("page_start", metadata.get("page_number", "")),
                "page_end": metadata.get("page_end", metadata.get("page_number", "")),
                "cosine_distance": float(distance),
                "expected_source_match": int(source_match),
                "human_relevant": "",
                "review_notes": "",
                "chunk_text": document,
            })

        hit_at_5 = int(bool(expected_ranks))
        reciprocal_rank = 1 / min(expected_ranks) if expected_ranks else 0.0

        summary_rows.append({
            "query_id": item["id"],
            "query": item["query"],
            "expected_source": item["expected_source"],
            "hit_at_5": hit_at_5,
            "expected_source_rank": min(expected_ranks) if expected_ranks else "",
            "reciprocal_rank": reciprocal_rank,
            "expected_source_chunks_in_top5": expected_matches,
            "unique_sources_in_top5": len(distinct_sources),
        })

        print(
            f"{item['id']}: Hit@5={hit_at_5}, "
            f"expected source rank="
            f"{min(expected_ranks) if expected_ranks else 'NOT FOUND'}"
        )

    def write_csv(path, rows):
        with path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=list(rows[0].keys()),
            )
            writer.writeheader()
            writer.writerows(rows)

    write_csv(candidates_file, candidate_rows)
    write_csv(summary_file, summary_rows)

    hit_rate = sum(r["hit_at_5"] for r in summary_rows) / len(summary_rows)
    mrr = sum(r["reciprocal_rank"] for r in summary_rows) / len(summary_rows)

    print("\n" + "=" * 65)
    print("INITIAL SOURCE-LEVEL RELEVANCE EVALUATION")
    print("=" * 65)
    print(f"Distinct queries: {len(summary_rows)}")
    print(f"Expected source Hit@5: {hit_rate:.3f}")
    print(f"Expected source MRR: {mrr:.3f}")
    print(f"Candidate result rows: {len(candidate_rows)}")
    print(f"Human review template: {candidates_file}")
    print(f"Query summary: {summary_file}")
    print("\nIMPORTANT:")
    print("These are source-level proxy metrics, not human relevance scores.")
    print("Review expected labels and mark human_relevant as 1 or 0.")
    print("The human relevance column has been left blank intentionally.")


if __name__ == "__main__":
    main()
