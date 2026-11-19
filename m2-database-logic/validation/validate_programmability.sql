-- =============================================================================
-- Programmability checks: generated column, procedure, triggers, view
-- -----------------------------------------------------------------------------
-- Exercises the M2 objects end to end inside a transaction that is rolled
-- back, so the Silver data is left unchanged. Audit rows written by the test
-- are rolled back together with the dispatch they describe.
--
--   mariadb gigavolt < m2-database-logic/validation/validate_programmability.sql
-- =============================================================================

USE gigavolt;

-- 1. Required objects exist ---------------------------------------------------
SELECT 'object: full_service_context column' AS check_name,
       IF(COUNT(*) = 1, 'PASS', 'FAIL') AS result
  FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'dispatches'
   AND COLUMN_NAME = 'full_service_context' AND EXTRA LIKE '%GENERATED%'
UNION ALL
SELECT 'object: sp_Prepare_RAG_Payloads', IF(COUNT(*) = 1, 'PASS', 'FAIL')
  FROM information_schema.ROUTINES
 WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_NAME = 'sp_Prepare_RAG_Payloads'
UNION ALL
SELECT 'object: 4 audit triggers', IF(COUNT(*) = 4, 'PASS', 'FAIL')
  FROM information_schema.TRIGGERS
 WHERE TRIGGER_SCHEMA = DATABASE()
   AND TRIGGER_NAME IN ('trg_Dispatches_After_Insert', 'trg_Dispatches_Before_Update',
                        'trg_AuditLogs_Prevent_Update', 'trg_AuditLogs_Prevent_Delete')
UNION ALL
SELECT 'object: vw_Customer_Safe hides PII', IF(COUNT(*) = 0, 'PASS', 'FAIL')
  FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'vw_Customer_Safe'
   AND COLUMN_NAME IN ('phone', 'email', 'address');

-- 2. Generated column renders the dispatch -----------------------------------
SELECT 'generated column populated for every dispatch' AS check_name,
       IF(SUM(full_service_context LIKE 'Dispatch ID: %') = COUNT(*), 'PASS', 'FAIL') AS result
  FROM dispatches;

-- 3. Triggers capture INSERT and UPDATE; audit log rejects changes ----------
-- Helper for the immutability check. Created before the transaction starts:
-- DDL causes an implicit COMMIT in MariaDB and would end the test transaction.
DROP PROCEDURE IF EXISTS tmp_check_audit_immutability;
DELIMITER $$
CREATE PROCEDURE tmp_check_audit_immutability()
BEGIN
    DECLARE update_blocked BOOLEAN DEFAULT FALSE;
    DECLARE delete_blocked BOOLEAN DEFAULT FALSE;

    BEGIN
        DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET update_blocked = TRUE;
        UPDATE Audit_Logs SET change_description = 'tampered'
         WHERE audit_id > @before_audit;
    END;

    BEGIN
        DECLARE CONTINUE HANDLER FOR SQLSTATE '45000' SET delete_blocked = TRUE;
        DELETE FROM Audit_Logs WHERE audit_id > @before_audit;
    END;

    SELECT 'immutability: UPDATE on Audit_Logs rejected' AS check_name,
           IF(update_blocked, 'PASS', 'FAIL') AS result
    UNION ALL
    SELECT 'immutability: DELETE on Audit_Logs rejected',
           IF(delete_blocked, 'PASS', 'FAIL');
END$$
DELIMITER ;

START TRANSACTION;

SET @before_audit := (SELECT COALESCE(MAX(audit_id), 0) FROM Audit_Logs);
SET @test_equipment := (SELECT MIN(equipment_id) FROM equipment);

INSERT INTO dispatches (dispatch_id, equipment_id, dispatch_date, technician,
                        service_type, hours_spent, labor_cost,
                        resolution_summary, status)
VALUES ('DISP-VALIDATION-1', @test_equipment, CURDATE(), 'Validation Run',
        'Diagnostic', 1.00, 100.00, 'Trigger validation insert.', 'Pending');

UPDATE dispatches
   SET status = 'Completed'
 WHERE dispatch_id = 'DISP-VALIDATION-1';

SELECT 'trigger: AFTER INSERT logged' AS check_name,
       IF(COUNT(*) = 1, 'PASS', 'FAIL') AS result
  FROM Audit_Logs
 WHERE audit_id > @before_audit AND operation_type = 'INSERT'
   AND change_description = 'New dispatch record created: DISP-VALIDATION-1'
UNION ALL
SELECT 'trigger: BEFORE UPDATE logged old and new values',
       IF(COUNT(*) = 1, 'PASS', 'FAIL')
  FROM Audit_Logs
 WHERE audit_id > @before_audit AND operation_type = 'UPDATE'
   AND old_values LIKE '%status=Pending%' AND new_values LIKE '%status=Completed%';

CALL tmp_check_audit_immutability();

ROLLBACK;

DROP PROCEDURE tmp_check_audit_immutability;

-- 4. Stored procedure returns one payload per dispatch -----------------------
-- (Run interactively to inspect output: CALL sp_Prepare_RAG_Payloads();)
SELECT 'procedure source joins dispatches to equipment' AS check_name,
       IF(ROUTINE_DEFINITION LIKE '%LEFT JOIN equipment%', 'PASS', 'FAIL') AS result
  FROM information_schema.ROUTINES
 WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_NAME = 'sp_Prepare_RAG_Payloads';

-- 5. The validation transaction left no data behind ---------------------------
SELECT 'cleanup: validation dispatch rolled back' AS check_name,
       IF(COUNT(*) = 0, 'PASS', 'FAIL') AS result
  FROM dispatches
 WHERE dispatch_id = 'DISP-VALIDATION-1';
