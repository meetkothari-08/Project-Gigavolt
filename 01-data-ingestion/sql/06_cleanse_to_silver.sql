-- =============================================================================
-- Bronze -> staging -> quarantine -> Silver cleansing pipeline
-- -----------------------------------------------------------------------------
-- Uses the functions in 04_cleansing_functions.sql (clean_text, clean_date,
-- clean_money). Run after 05_load_bronze.sql; scripts/deploy_database.sh --raw-dir runs both.
--
-- 1. Typed staging rows, each keeping its bronze_row_id for lineage
-- 2. Deduplicate on the business key, keeping the most recent row
--    (highest bronze_row_id); pre-dedup equipment kept as an audit snapshot
-- 3. Quarantine dispatches whose equipment does not exist, then load Silver;
--    warranty claims that point at a quarantined dispatch keep the claim and
--    null the dangling reference (logged in warranty_claims_quarantine)
--
-- The cleansing rules evolved from the first version of this pipeline
-- (legacy_v1/03_clean.sql). Idempotent: staging, quarantine and Silver
-- tables are emptied first. Expected Silver counts: 500 / 2,500 / 5 / 4,941 /
-- 150 / 1,200, with 59 dispatches quarantined.
-- =============================================================================

USE gigavolt;
SET NAMES utf8mb4 COLLATE utf8mb4_uca1400_ai_ci;

-- -----------------------------------------------------------------------------
-- Reset staging, quarantine and Silver (children before parents)
-- -----------------------------------------------------------------------------
SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE silver_customers_staging;
TRUNCATE TABLE silver_equipment_staging;
TRUNCATE TABLE silver_equipment_before_dedup;
TRUNCATE TABLE silver_dispatches_staging;
TRUNCATE TABLE silver_parts_staging;
TRUNCATE TABLE silver_warranty_claims_staging;
TRUNCATE TABLE dispatches_quarantine;
TRUNCATE TABLE warranty_claims_quarantine;
TRUNCATE TABLE warranty_claims;
TRUNCATE TABLE dispatches;
TRUNCATE TABLE parts;
TRUNCATE TABLE equipment;
TRUNCATE TABLE equipment_models;
TRUNCATE TABLE customers;
SET FOREIGN_KEY_CHECKS = 1;

-- -----------------------------------------------------------------------------
-- 1. Typed staging
-- -----------------------------------------------------------------------------
INSERT INTO silver_customers_staging
SELECT
    bronze_row_id,
    TRIM(customer_id),
    clean_text(company_name),
    clean_text(contact_name),
    -- digits only; drop a leading country code 1 from 11-digit numbers
    REGEXP_REPLACE(REGEXP_REPLACE(clean_text(phone), '[^0-9]', ''), '^1([0-9]{10})$', '\\1'),
    LOWER(clean_text(email)),
    clean_text(address),
    clean_text(city),
    UPPER(clean_text(state)),
    -- restore leading zeros lost by spreadsheet export (2113 -> 02113)
    LPAD(clean_text(zip), 5, '0'),
    CASE WHEN UPPER(clean_text(country)) IN ('US', 'USA', 'UNITED STATES')
         THEN 'United States' END,
    clean_date(created_date),
    UPPER(clean_text(status))
FROM bronze_customers;

INSERT INTO silver_equipment_staging
SELECT
    bronze_row_id,
    TRIM(equipment_id),
    TRIM(customer_id),
    UPPER(clean_text(model)),
    clean_text(serial_number),
    clean_date(install_date),
    CAST(clean_text(capacity_kw) AS DECIMAL(10,2)),
    UPPER(clean_text(voltage)),
    clean_date(warranty_expiration),
    UPPER(clean_text(status)),
    clean_text(location_notes)
FROM bronze_equipment;

INSERT INTO silver_equipment_before_dedup SELECT * FROM silver_equipment_staging;

INSERT INTO silver_dispatches_staging
SELECT
    bronze_row_id,
    TRIM(dispatch_id),
    TRIM(equipment_id),
    TRIM(customer_id),
    clean_date(dispatch_date),
    clean_text(technician),
    clean_text(service_type),
    CAST(clean_text(hours_spent) AS DECIMAL(10,2)),
    clean_money(labor_cost),
    clean_text(resolution_summary),
    UPPER(clean_text(status))
FROM bronze_dispatches;

INSERT INTO silver_parts_staging
SELECT
    bronze_row_id,
    TRIM(part_id),
    clean_text(part_name),
    clean_text(category),
    clean_text(manufacturer),
    clean_text(supplier),
    clean_money(unit_cost),
    clean_money(unit_price),
    CAST(clean_text(stock_quantity) AS SIGNED),
    CAST(clean_text(reorder_level) AS SIGNED)
FROM bronze_parts;

INSERT INTO silver_warranty_claims_staging
SELECT
    bronze_row_id,
    TRIM(claim_id),
    TRIM(equipment_id),
    clean_text(dispatch_id),
    clean_text(part_id),
    clean_date(claim_date),
    clean_money(claim_amount),
    clean_money(approved_amount),
    UPPER(clean_text(status)),
    clean_text(denial_reason),
    clean_text(claim_notes)
FROM bronze_warranty_claims;

-- -----------------------------------------------------------------------------
-- 2 + 3. Deduplicate (latest bronze row wins), quarantine, load Silver
-- -----------------------------------------------------------------------------
INSERT INTO customers
    (customer_id, company_name, contact_name, phone, email, address,
     city, state, zip, country, created_date, status)
SELECT s.customer_id, s.company_name, s.contact_name, s.phone, s.email, s.address,
       s.city, s.state, s.zip, s.country, s.created_date, s.status
FROM silver_customers_staging s
JOIN (SELECT customer_id, MAX(bronze_row_id) AS keep_id
      FROM silver_customers_staging GROUP BY customer_id) k
  ON k.keep_id = s.bronze_row_id;

-- Model attributes depend on the model, not the unit (3NF).
INSERT INTO equipment_models (model, capacity_kw, voltage)
SELECT DISTINCT model, capacity_kw, voltage
FROM silver_equipment_staging;

INSERT INTO equipment
    (equipment_id, customer_id, model, serial_number, install_date,
     warranty_expiration, status, location_notes)
SELECT s.equipment_id, s.customer_id, s.model, s.serial_number, s.install_date,
       s.warranty_expiration, s.status, s.location_notes
FROM silver_equipment_staging s
JOIN (SELECT equipment_id, MAX(bronze_row_id) AS keep_id
      FROM silver_equipment_staging GROUP BY equipment_id) k
  ON k.keep_id = s.bronze_row_id;

-- Dispatches for equipment that does not exist are quarantined, not dropped.
INSERT INTO dispatches_quarantine
SELECT s.*, 'equipment_id not found in equipment'
FROM silver_dispatches_staging s
LEFT JOIN equipment e ON e.equipment_id = s.equipment_id
WHERE e.equipment_id IS NULL;

INSERT INTO dispatches
    (dispatch_id, equipment_id, dispatch_date, technician, service_type,
     hours_spent, labor_cost, resolution_summary, status)
SELECT s.dispatch_id, s.equipment_id, s.dispatch_date, s.technician, s.service_type,
       s.hours_spent, s.labor_cost, s.resolution_summary, s.status
FROM silver_dispatches_staging s
JOIN equipment e ON e.equipment_id = s.equipment_id
JOIN (SELECT dispatch_id, MAX(bronze_row_id) AS keep_id
      FROM silver_dispatches_staging GROUP BY dispatch_id) k
  ON k.keep_id = s.bronze_row_id;

INSERT INTO parts
    (part_id, part_name, category, manufacturer, supplier,
     unit_cost, unit_price, stock_quantity, reorder_level)
SELECT s.part_id, s.part_name, s.category, s.manufacturer, s.supplier,
       s.unit_cost, s.unit_price, s.stock_quantity, s.reorder_level
FROM silver_parts_staging s
JOIN (SELECT part_id, MAX(bronze_row_id) AS keep_id
      FROM silver_parts_staging GROUP BY part_id) k
  ON k.keep_id = s.bronze_row_id;

-- Claims keep their row even when an optional reference is dangling; the
-- reference is nulled and the decision is logged for audit.
INSERT INTO warranty_claims_quarantine
    (bronze_row_id, claim_id, equipment_id, dispatch_id, part_id, quarantine_reason)
SELECT s.bronze_row_id, s.claim_id, s.equipment_id, s.dispatch_id, s.part_id,
       CASE WHEN d.dispatch_id IS NULL AND s.dispatch_id IS NOT NULL
            THEN 'dispatch_id not found in dispatches; reference nulled'
            ELSE 'part_id not found in parts; reference nulled' END
FROM silver_warranty_claims_staging s
JOIN (SELECT claim_id, MAX(bronze_row_id) AS keep_id
      FROM silver_warranty_claims_staging GROUP BY claim_id) k
  ON k.keep_id = s.bronze_row_id
LEFT JOIN dispatches d ON d.dispatch_id = s.dispatch_id
LEFT JOIN parts p ON p.part_id = s.part_id
WHERE (s.dispatch_id IS NOT NULL AND d.dispatch_id IS NULL)
   OR (s.part_id IS NOT NULL AND p.part_id IS NULL);

INSERT INTO warranty_claims
    (claim_id, equipment_id, dispatch_id, part_id, claim_date, claim_amount,
     approved_amount, status, denial_reason, claim_notes)
SELECT s.claim_id, s.equipment_id, d.dispatch_id, p.part_id, s.claim_date,
       s.claim_amount, s.approved_amount, s.status, s.denial_reason, s.claim_notes
FROM silver_warranty_claims_staging s
JOIN (SELECT claim_id, MAX(bronze_row_id) AS keep_id
      FROM silver_warranty_claims_staging GROUP BY claim_id) k
  ON k.keep_id = s.bronze_row_id
LEFT JOIN dispatches d ON d.dispatch_id = s.dispatch_id
LEFT JOIN parts p ON p.part_id = s.part_id;

-- -----------------------------------------------------------------------------
-- Summary: Bronze -> Silver reconciliation
-- -----------------------------------------------------------------------------
SELECT 'customers' AS entity,
       (SELECT COUNT(*) FROM bronze_customers) AS bronze_rows,
       (SELECT COUNT(*) FROM customers) AS silver_rows,
       0 AS quarantined
UNION ALL SELECT 'equipment', (SELECT COUNT(*) FROM bronze_equipment),
       (SELECT COUNT(*) FROM equipment), 0
UNION ALL SELECT 'equipment_models', NULL, (SELECT COUNT(*) FROM equipment_models), 0
UNION ALL SELECT 'dispatches', (SELECT COUNT(*) FROM bronze_dispatches),
       (SELECT COUNT(*) FROM dispatches), (SELECT COUNT(*) FROM dispatches_quarantine)
UNION ALL SELECT 'parts', (SELECT COUNT(*) FROM bronze_parts), (SELECT COUNT(*) FROM parts), 0
UNION ALL SELECT 'warranty_claims', (SELECT COUNT(*) FROM bronze_warranty_claims),
       (SELECT COUNT(*) FROM warranty_claims), (SELECT COUNT(*) FROM warranty_claims_quarantine);
