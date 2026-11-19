# Milestone 2 · SQL Programming, RAG Payloads & Audit Security

Builds logic directly into MariaDB on top of the Silver layer. A generated column and a stored procedure prepare service history as text the RAG engine can use. Triggers write every dispatch change to an immutable audit log, and a masking view keeps customer PII out of application queries.

| | |
|---|---|
| **Objects** | 1 generated column · 1 stored procedure · 4 triggers · 1 audit table · 1 masked view |
| **Validation** | 11 programmability checks, all passing (triggers fire, audit log rejects `UPDATE`/`DELETE`, view hides PII) |
| **Consumers** | The RAG engine ([Milestone 5](../m5-rag-assistant/)) and the audit-log cursor in the incremental pipeline ([Milestone 6](../m6-ops-evaluation/)) |

## What's here

| Path | Object | What it does |
|---|---|---|
| [`sql/01_generated_columns.sql`](sql/01_generated_columns.sql) | `dispatches.full_service_context` | A `VIRTUAL` generated column that renders each dispatch as a labelled text block for RAG. It is computed at read time, so it never drifts from the row and costs no storage. |
| [`sql/02_audit_log.sql`](sql/02_audit_log.sql) | `Audit_Logs` | An append-only change history. `BEFORE UPDATE` and `BEFORE DELETE` triggers raise `SQLSTATE 45000`, so audit rows cannot be altered or removed. |
| [`sql/03_audit_triggers.sql`](sql/03_audit_triggers.sql) | `trg_Dispatches_After_Insert`, `trg_Dispatches_Before_Update` | Capture the new row, and the before and after values, for every insert and update on `dispatches`. |
| [`sql/04_rag_payload_procedure.sql`](sql/04_rag_payload_procedure.sql) | `sp_Prepare_RAG_Payloads()` | Joins dispatches with equipment and returns one labelled service-history payload per dispatch. |
| [`sql/05_security_views.sql`](sql/05_security_views.sql) | `vw_Customer_Safe` | Column-level masking: customer attributes without phone, email or street address, plus least-privilege grant templates. |
| [`validation/validate_programmability.sql`](validation/validate_programmability.sql) | | 11 end-to-end checks (below) |

## Run it

```bash
# From the repo root (deploys Milestone 1 first, then these objects, then all checks)
scripts/deploy_database.sh --raw-dir data/raw/erp --validate

# Inspect the RAG payloads
mariadb gigavolt -e "CALL sp_Prepare_RAG_Payloads();" | head
```

## Example output

```
=== SERVICE RECORD ===
Dispatch ID: DISP-10001
Equipment ID: EQ-5805
Equipment Model: X-12000
Service Date: 2024-03-21
Technician: Mike Johnson
Service Type: Diagnostic
Hours Spent: 3.20
Labor Cost: 384.00
Resolution: Emergency dispatch for over-temperature alarm. Cleaned heat exchanger.
Status: PENDING
```

## How the checks work

[`validation/validate_programmability.sql`](validation/validate_programmability.sql) does more than check that objects exist:

1. **Objects:** confirms the generated column, the procedure, all 4 triggers and the view exist, and that the view exposes none of `phone`, `email` or `address`.
2. **Generated column:** confirms every one of the 4,941 dispatches renders a service-context block.
3. **Triggers:** inside a transaction, inserts a test dispatch and updates its status, then checks that `Audit_Logs` gained an `INSERT` row and an `UPDATE` row carrying the old and new values.
4. **Immutability:** attempts an `UPDATE` and a `DELETE` on `Audit_Logs` and checks that both are rejected with `SQLSTATE 45000`.
5. **Clean-up:** rolls the transaction back and checks that no test data remains. The helper procedure is created *before* the transaction, because DDL in MariaDB causes an implicit commit.

## Design notes

* **Virtual, not stored.** The service-context column is derived from other columns of the same row, so a `VIRTUAL` column gives the RAG layer one field to read with zero storage and zero drift.
* **Audit on `dispatches`.** Service events are the records that change after the fact (status updates, resolutions). The audit log doubles as the change feed that the [incremental relational pipeline](../m6-ops-evaluation/) reads with an `audit_id` checkpoint.
* **Immutability in the database.** Rejecting `UPDATE` and `DELETE` with triggers means even the account that wrote an audit row cannot rewrite history through SQL.
* **Masking through a view.** Applications are granted `SELECT` on `vw_Customer_Safe`, not on `customers`, so PII stays out of RAG prompts by construction.
