-- =============================================================================
-- Generated column: full_service_context
-- -----------------------------------------------------------------------------
-- A VIRTUAL generated column that renders each dispatch as a labelled text
-- block. Downstream RAG code can read one column instead of re-implementing
-- the formatting, and the text always reflects the current row because it is
-- computed at read time (no storage cost, no drift).
-- =============================================================================

USE gigavolt;

ALTER TABLE dispatches
    ADD COLUMN IF NOT EXISTS full_service_context TEXT
    GENERATED ALWAYS AS (
        CONCAT_WS('\n',
            CONCAT('Dispatch ID: ', dispatch_id),
            CONCAT('Equipment ID: ', equipment_id),
            CONCAT('Service Date: ', dispatch_date),
            CONCAT('Technician: ', COALESCE(technician, 'Not Assigned')),
            CONCAT('Service Type: ', service_type),
            CONCAT('Hours Spent: ', hours_spent),
            CONCAT('Labor Cost: ', labor_cost),
            CONCAT('Resolution: ', COALESCE(resolution_summary, 'No resolution provided')),
            CONCAT('Status: ', status)
        )
    ) VIRTUAL;
