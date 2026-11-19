-- =============================================================================
-- Change-capture triggers on dispatches
-- -----------------------------------------------------------------------------
--   AFTER INSERT  -> logs the new row
--   BEFORE UPDATE -> logs the pre-change and post-change values
--
-- The relational ingestion pipeline (m6-ops-evaluation/gigavolt/ingestion/relational) reads
-- these audit rows incrementally using an audit_id checkpoint.
-- =============================================================================

USE gigavolt;

DROP TRIGGER IF EXISTS trg_Dispatches_After_Insert;
DROP TRIGGER IF EXISTS trg_Dispatches_Before_Update;

DELIMITER $$

CREATE TRIGGER trg_Dispatches_After_Insert
AFTER INSERT ON dispatches
FOR EACH ROW
BEGIN
    INSERT INTO Audit_Logs (
        changed_by, table_name, operation_type,
        old_values, new_values, change_description
    )
    VALUES (
        CURRENT_USER(),
        'dispatches',
        'INSERT',
        NULL,
        CONCAT(
            'dispatch_id=', NEW.dispatch_id,
            ', equipment_id=', NEW.equipment_id,
            ', dispatch_date=', NEW.dispatch_date,
            ', technician=', COALESCE(NEW.technician, 'Not Assigned'),
            ', service_type=', NEW.service_type,
            ', hours_spent=', NEW.hours_spent,
            ', labor_cost=', NEW.labor_cost,
            ', resolution_summary=', COALESCE(NEW.resolution_summary, 'No resolution provided'),
            ', status=', NEW.status
        ),
        CONCAT('New dispatch record created: ', NEW.dispatch_id)
    );
END$$

CREATE TRIGGER trg_Dispatches_Before_Update
BEFORE UPDATE ON dispatches
FOR EACH ROW
BEGIN
    INSERT INTO Audit_Logs (
        changed_by, table_name, operation_type,
        old_values, new_values, change_description
    )
    VALUES (
        CURRENT_USER(),
        'dispatches',
        'UPDATE',
        CONCAT(
            'dispatch_id=', OLD.dispatch_id,
            ', equipment_id=', OLD.equipment_id,
            ', dispatch_date=', OLD.dispatch_date,
            ', technician=', COALESCE(OLD.technician, 'Not Assigned'),
            ', service_type=', OLD.service_type,
            ', hours_spent=', OLD.hours_spent,
            ', labor_cost=', OLD.labor_cost,
            ', resolution_summary=', COALESCE(OLD.resolution_summary, 'No resolution provided'),
            ', status=', OLD.status
        ),
        CONCAT(
            'dispatch_id=', NEW.dispatch_id,
            ', equipment_id=', NEW.equipment_id,
            ', dispatch_date=', NEW.dispatch_date,
            ', technician=', COALESCE(NEW.technician, 'Not Assigned'),
            ', service_type=', NEW.service_type,
            ', hours_spent=', NEW.hours_spent,
            ', labor_cost=', NEW.labor_cost,
            ', resolution_summary=', COALESCE(NEW.resolution_summary, 'No resolution provided'),
            ', status=', NEW.status
        ),
        CONCAT('Dispatch record updated: ', OLD.dispatch_id)
    );
END$$

DELIMITER ;
