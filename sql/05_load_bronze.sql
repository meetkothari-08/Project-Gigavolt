-- =============================================================================
-- Load the raw ERP CSV extracts into the Bronze tables
-- -----------------------------------------------------------------------------
-- Run from the directory that holds the five CSVs (sql/deploy.sh --raw-dir does
-- this), because LOAD DATA LOCAL resolves relative paths against the client's
-- working directory. Requires local_infile enabled on server and client.
--
-- The extracts are CRLF-terminated, so LINES TERMINATED BY '\r\n' is required:
-- with the default '\n' the carriage return stays glued to the last column of
-- every row (a defect found in an earlier load; see docs/data-platform.md).
--
-- Expected Bronze row counts: customers 525, equipment 2,575, dispatches 5,000,
-- parts 150, warranty_claims 1,248.
-- =============================================================================

USE gigavolt;

TRUNCATE TABLE bronze_customers;
TRUNCATE TABLE bronze_equipment;
TRUNCATE TABLE bronze_dispatches;
TRUNCATE TABLE bronze_parts;
TRUNCATE TABLE bronze_warranty_claims;

LOAD DATA LOCAL INFILE 'customers.csv'
    INTO TABLE bronze_customers CHARACTER SET utf8mb4
    FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
    LINES TERMINATED BY '\r\n' IGNORE 1 LINES
    (customer_id, company_name, contact_name, phone, email, address,
     city, state, zip, country, created_date, status);

LOAD DATA LOCAL INFILE 'equipment.csv'
    INTO TABLE bronze_equipment CHARACTER SET utf8mb4
    FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
    LINES TERMINATED BY '\r\n' IGNORE 1 LINES
    (equipment_id, customer_id, model, serial_number, install_date,
     capacity_kw, voltage, warranty_expiration, status, location_notes);

LOAD DATA LOCAL INFILE 'dispatches.csv'
    INTO TABLE bronze_dispatches CHARACTER SET utf8mb4
    FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
    LINES TERMINATED BY '\r\n' IGNORE 1 LINES
    (dispatch_id, equipment_id, customer_id, dispatch_date, technician,
     service_type, hours_spent, labor_cost, resolution_summary, status);

LOAD DATA LOCAL INFILE 'parts.csv'
    INTO TABLE bronze_parts CHARACTER SET utf8mb4
    FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
    LINES TERMINATED BY '\r\n' IGNORE 1 LINES
    (part_id, part_name, category, manufacturer, supplier,
     unit_cost, unit_price, stock_quantity, reorder_level);

LOAD DATA LOCAL INFILE 'warranty_claims.csv'
    INTO TABLE bronze_warranty_claims CHARACTER SET utf8mb4
    FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
    LINES TERMINATED BY '\r\n' IGNORE 1 LINES
    (claim_id, equipment_id, dispatch_id, part_id, claim_date,
     claim_amount, approved_amount, status, denial_reason, claim_notes);

SELECT 'bronze_customers' AS bronze_table, COUNT(*) AS row_count FROM bronze_customers
UNION ALL SELECT 'bronze_equipment',       COUNT(*) FROM bronze_equipment
UNION ALL SELECT 'bronze_dispatches',      COUNT(*) FROM bronze_dispatches
UNION ALL SELECT 'bronze_parts',           COUNT(*) FROM bronze_parts
UNION ALL SELECT 'bronze_warranty_claims', COUNT(*) FROM bronze_warranty_claims;
