-- =============================================================================
-- sp_Prepare_RAG_Payloads
-- -----------------------------------------------------------------------------
-- Joins every dispatch with its equipment record and renders a labelled
-- service-history block (`rag_payload`) that can be embedded or passed to an
-- LLM directly, so application code never has to rebuild the join.
--
-- Usage:  CALL sp_Prepare_RAG_Payloads();
-- =============================================================================

USE gigavolt;

DROP PROCEDURE IF EXISTS sp_Prepare_RAG_Payloads;

DELIMITER $$

CREATE PROCEDURE sp_Prepare_RAG_Payloads()
BEGIN
    SELECT
        d.dispatch_id,
        CONCAT_WS('\n',
            '=== SERVICE RECORD ===',
            CONCAT('Dispatch ID: ', d.dispatch_id),
            CONCAT('Equipment ID: ', d.equipment_id),
            CONCAT('Equipment Model: ', COALESCE(e.model, 'Unknown')),
            CONCAT('Service Date: ', d.dispatch_date),
            CONCAT('Technician: ', COALESCE(d.technician, 'Not Assigned')),
            CONCAT('Service Type: ', d.service_type),
            CONCAT('Hours Spent: ', d.hours_spent),
            CONCAT('Labor Cost: ', d.labor_cost),
            CONCAT('Resolution: ', COALESCE(d.resolution_summary, 'No resolution provided')),
            CONCAT('Status: ', d.status)
        ) AS rag_payload
    FROM dispatches d
    LEFT JOIN equipment e
        ON d.equipment_id = e.equipment_id;
END$$

DELIMITER ;
