# Milestone 5 · Multi-Model Integration & Hybrid RAG Engine

A natural-language question is routed to three stores: **MariaDB** (equipment, service history, warranty, parts), **MongoDB** (BMS telemetry and fault events) and **ChromaDB** (technical documents). The evidence goes to a local LLM (Ollama · Phi), and every citation in the answer is checked against the sources actually retrieved.

| | |
|---|---|
| **Stores** | MariaDB · MongoDB · ChromaDB, each with retry + reconnect |
| **Routing** | Entity extraction (`EQ-…`, `SN-…`) + keyword routes; one failing store degrades, never fails, a request |
| **Retrieval** | ≈ **0.05 s** median across all three stores |
| **Provenance** | Cited IDs validated against retrieved IDs; claim-level audit separates model citations from the fallback list |

> The graph-database component in the original course specification was removed from the requirements by the instructor, so retrieval covers three stores.

## What's here

| Path | Contents |
|---|---|
| [`gigavolt/config.py`](gigavolt/config.py) | Every endpoint, credential and path read from the environment |
| [`gigavolt/retrieval/`](gigavolt/retrieval/) | MariaDB, MongoDB and ChromaDB retrievers |
| [`gigavolt/rag/engine.py`](gigavolt/rag/engine.py) | Routing, retrieval, deduplication, prompt budget, answer, provenance |
| [`gigavolt/rag/generator.py`](gigavolt/rag/generator.py) · [`prompts.py`](gigavolt/rag/prompts.py) | Grounded generation through Ollama |
| [`gigavolt/rag/provenance.py`](gigavolt/rag/provenance.py) | Citation validation |
| [`gigavolt/cli.py`](gigavolt/cli.py) | `gigavolt-ask` command-line assistant |

## Run it

```bash
pip install -e .
cp .env.example .env        # MariaDB, MongoDB, ChromaDB, embedding API and Ollama endpoints
gigavolt-ask "Show the service history and warranty claims for EQ-5508"
gigavolt-ask --json "Are there high-temperature telemetry observations for the X-7000?"
```

## Request flow

```
question
   │
   ├─ entity extraction ── EQ-#### (equipment ID) / SN-… (serial number)
   ├─ keyword routing ──── "x-7000", "supplier|lithium|cell", "part|stock|inventory|reorder"
   ▼
retrieve()  ─────────────────────────────────────────────────────────────
   1. ChromaDB   top-3 chunks for the question (always)
   2. MariaDB    equipment + customer + model, last 3 dispatches, last 3 claims   (if ID found)
   3. MongoDB    last 5 readings + fault events for the unit's serial number       (if ID found)
   4. MongoDB    model telemetry and readings ≥ 40 °C                              (if "x-7000")
   5. MariaDB    lithium-cell components and suppliers                             (supply-chain words)
   6. MariaDB    parts at or below reorder level                                   (inventory words)
   7. dedupe by document ID (highest-priority route wins), cap telemetry at 3
   ▼
generate()  ── compact evidence (3 docs, 2 relational, 3 telemetry) → Ollama/Phi, temperature 0
   ▼
verify_citations()  ── cited IDs vs IDs actually retrieved
```

Every retrieved item carries a typed source ID (`equipment:EQ-5508`, `dispatch:DISP-10234`, `warranty:CLM-…`, `part:PRT-2007`, `telemetry:<ObjectId>`, `fault:<ObjectId>`, or a chunk ID such as `f3159dbf5de4b71b-c0001`). The model is told to copy these IDs into square brackets after each claim.

Each route catches its own exceptions and records them in `context["errors"]`. If MongoDB is down, the answer is still built from MariaDB and ChromaDB, and the failure is reported with it.

## Store responsibilities

| Store | Why this engine | Access pattern |
|---|---|---|
| MariaDB | Relational ERP entities with enforced foreign keys; joins across equipment, customers, models, dispatches and claims | Point lookups by key, ordered history, allow-listed text search |
| MongoDB | Telemetry is nested, schema-flexible JSON (readings, flagged components, notes) | Equipment + time range, fault code, model regex, temperature threshold |
| ChromaDB | Semantic similarity over unstructured manuals and SOPs | k-NN over E5 embeddings; metadata filter by source document |

The relational retriever only reads an allow-list of six tables. Table and column names in dynamic SQL come from that allow-list and from `INFORMATION_SCHEMA`, never from user input, and all values are parameterized. Every client retries transient connection errors (MySQL codes 2006, 2013 and 2055; Mongo `AutoReconnect`; Chroma transport errors; embedding API 429/5xx) with reconnect and linear backoff.

## Generation settings

Phi runs locally through Ollama with `temperature = 0`, `num_ctx = 1024` and `num_predict = 80`, so answers are repeatable and the prompt fits the context window. The evidence budget (document excerpts cut to 300 characters, 2 relational records, 3 telemetry readings) keeps the prompt inside that window. The system prompt ([`rag/prompts.py`](gigavolt/rag/prompts.py)) forbids unsupported claims. It also requires the model to keep documented diagnostic indicators separate from observed telemetry and from confirmed failures, and to state what evidence is missing.

## Provenance and the citation audit

[`rag/provenance.py`](gigavolt/rag/provenance.py) compares every bracketed ID in the answer with the catalog of IDs actually retrieved for that question. This checks identifiers, not meaning: a valid citation proves the source was in the context, not that it supports the sentence it follows.

When the model cites nothing, the generator appends a `Retrieved Sources:` list so the reader can still see the evidence. Re-auditing the saved benchmark answers showed that the original metric counted that appended list as if the model had cited it. The checker was fixed to:

* score the model-written text separately from the appended fallback list (`model_citations_*` fields), and
* split comma-separated IDs inside one bracket (`[telemetry:a, telemetry:b]`).

Re-scoring the 20 saved answers from the 2026-11-15 run with [`audit_saved_answers.py`](../m6-ops-evaluation/benchmark/audit_saved_answers.py) gives the claim-level picture ([report](../m6-ops-evaluation/results/citation_audit_20261115_075228.json)):

| | Answers (of 20) |
|---|---:|
| Fallback source list appended | 20 |
| Model wrote at least one bracket | 9 |
| …containing a well-formed source ID | 4 |
| …containing prose or copied evidence instead of an ID | 6 |
| Only clean, well-formed model citations | 3 |

The headline numbers in the original summaries (citation presence 100%, valid-citation rate 55%) describe the whole answer, fallback included. **At claim level, a 2.7B-parameter local model with an 80-token output budget rarely cites reliably.** Every answer is still traceable through the retrieved-source list, but answer-level provenance is the main open issue (see [Milestone 6 · Next steps](../m6-ops-evaluation/#next-steps)).
