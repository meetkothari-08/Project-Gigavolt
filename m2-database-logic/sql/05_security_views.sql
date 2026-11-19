-- =============================================================================
-- Column-level data masking
-- -----------------------------------------------------------------------------
-- vw_Customer_Safe exposes customer attributes needed for reporting and RAG
-- context while omitting direct identifiers (phone, email, street address).
-- Consumers are granted SELECT on the view, not on the base table.
-- =============================================================================

USE gigavolt;

CREATE OR REPLACE
    SQL SECURITY DEFINER
VIEW vw_Customer_Safe AS
SELECT
    customer_id,
    company_name,
    contact_name,
    city,
    state,
    zip,
    country,
    created_date,
    status
FROM customers;

-- Example grants (run as an administrator; replace the placeholder passwords):
--
-- CREATE USER IF NOT EXISTS 'gigavolt_analyst'@'%' IDENTIFIED BY '<change-me>';
-- GRANT SELECT ON gigavolt.vw_Customer_Safe TO 'gigavolt_analyst'@'%';
--
-- CREATE USER IF NOT EXISTS 'gigavolt_app'@'%' IDENTIFIED BY '<change-me>';
-- GRANT SELECT ON gigavolt.equipment        TO 'gigavolt_app'@'%';
-- GRANT SELECT ON gigavolt.equipment_models TO 'gigavolt_app'@'%';
-- GRANT SELECT ON gigavolt.dispatches       TO 'gigavolt_app'@'%';
-- GRANT SELECT ON gigavolt.parts            TO 'gigavolt_app'@'%';
-- GRANT SELECT ON gigavolt.warranty_claims  TO 'gigavolt_app'@'%';
-- GRANT SELECT ON gigavolt.vw_Customer_Safe TO 'gigavolt_app'@'%';
-- GRANT SELECT ON gigavolt.Audit_Logs       TO 'gigavolt_app'@'%';
