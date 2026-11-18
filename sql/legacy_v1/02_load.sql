USE gigavolt_erp;

TRUNCATE TABLE import_customers;
TRUNCATE TABLE import_equipment;
TRUNCATE TABLE import_dispatches;
TRUNCATE TABLE import_parts;
TRUNCATE TABLE import_warranty_claims;

-- Source CSVs are CRLF-terminated, so LINES TERMINATED BY '\r\n' is required
-- (not the MariaDB default '\n'); IGNORE 1 LINES skips the header row.
LOAD DATA LOCAL INFILE '/tmp/data/customers.csv' INTO TABLE import_customers CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\r\n' IGNORE 1 LINES (customer_id, company_name, contact_name, phone, email, address, city, state, zip, country, created_date, status);

LOAD DATA LOCAL INFILE '/tmp/data/equipment.csv' INTO TABLE import_equipment CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\r\n' IGNORE 1 LINES (equipment_id, customer_id, model, serial_number, install_date, capacity_kw, voltage, warranty_expiration, status, location_notes);

LOAD DATA LOCAL INFILE '/tmp/data/dispatches.csv' INTO TABLE import_dispatches CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\r\n' IGNORE 1 LINES (dispatch_id, equipment_id, customer_id, dispatch_date, technician, service_type, hours_spent, labor_cost, resolution_summary, status);

LOAD DATA LOCAL INFILE '/tmp/data/parts.csv' INTO TABLE import_parts CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\r\n' IGNORE 1 LINES (part_id, part_name, category, manufacturer, supplier, unit_cost, unit_price, stock_quantity, reorder_level);

LOAD DATA LOCAL INFILE '/tmp/data/warranty_claims.csv' INTO TABLE import_warranty_claims CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\r\n' IGNORE 1 LINES (claim_id, equipment_id, dispatch_id, part_id, claim_date, claim_amount, approved_amount, status, denial_reason, claim_notes);

-- Expected staging row counts: import_customers 525, import_equipment 2575,
-- import_dispatches 5000, import_parts 150, import_warranty_claims 1248.
SELECT 'import_customers' AS staging_table, COUNT(*) AS row_count FROM import_customers
UNION ALL
SELECT 'import_equipment', COUNT(*) FROM import_equipment
UNION ALL
SELECT 'import_dispatches', COUNT(*) FROM import_dispatches
UNION ALL
SELECT 'import_parts', COUNT(*) FROM import_parts
UNION ALL
SELECT 'import_warranty_claims', COUNT(*) FROM import_warranty_claims;

