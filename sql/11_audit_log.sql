-- =============================================================================
-- Immutable audit log
-- -----------------------------------------------------------------------------
-- Append-only change history. BEFORE UPDATE / BEFORE DELETE triggers raise
-- SQLSTATE 45000, so rows cannot be altered or removed through DML, even by
-- the account that inserted them.
-- =============================================================================

USE gigavolt;

CREATE TABLE IF NOT EXISTS Audit_Logs (
    audit_id            BIGINT       NOT NULL AUTO_INCREMENT,
    audit_timestamp     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changed_by          VARCHAR(255) NOT NULL,
    table_name          VARCHAR(100) NOT NULL,
    operation_type      VARCHAR(20)  NOT NULL,
    old_values          LONGTEXT     DEFAULT NULL,
    new_values          LONGTEXT     DEFAULT NULL,
    change_description  TEXT         DEFAULT NULL,
    PRIMARY KEY (audit_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_uca1400_ai_ci;

DROP TRIGGER IF EXISTS trg_AuditLogs_Prevent_Update;
DROP TRIGGER IF EXISTS trg_AuditLogs_Prevent_Delete;

DELIMITER $$

CREATE TRIGGER trg_AuditLogs_Prevent_Update
BEFORE UPDATE ON Audit_Logs
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Audit_Logs is immutable and cannot be updated';
END$$

CREATE TRIGGER trg_AuditLogs_Prevent_Delete
BEFORE DELETE ON Audit_Logs
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Audit_Logs is immutable and cannot be deleted';
END$$

DELIMITER ;
