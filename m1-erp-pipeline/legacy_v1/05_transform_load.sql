-- 05_transform_load.sql: Bronze import_* -> Silver 3NF (same table order as 04_prod_schema.sql).
-- Dedup keeps the first-loaded row: JOIN to (SELECT MIN(stg_row_id) m ... GROUP BY <business key>).
-- dispatches and parts have 0 duplicate rows (verified during profiling) so they skip the dedup JOIN.
-- Orphan dispatches (equipment_id absent from equipment_units) are quarantined into
-- rejected_dispatches BEFORE service_logs is loaded, so every service_logs FK resolves.
-- Column lists are omitted: each SELECT lists columns in exact target-table order.
-- 03_clean.sql already produced ISO 'YYYY-MM-DD' dates and bare numeric strings, so the
-- implicit string->DATE / string->DECIMAL cast on INSERT is exact.
-- Idempotent: 04_prod_schema.sql recreates these tables empty immediately before this runs.
USE gigavolt_erp;
-- locations: zip functionally determines (city,state)
INSERT INTO locations SELECT DISTINCT zip,city,state FROM import_customers WHERE zip IS NOT NULL;
-- equipment_models: model functionally determines (capacity_kw,voltage)
INSERT INTO equipment_models SELECT DISTINCT model,capacity_kw,voltage FROM import_equipment;
-- customers: dedup on customer_id (25 duplicate rows in staging)
INSERT INTO customers SELECT c.customer_id,c.company_name,c.contact_name,c.phone,c.email,c.address,c.zip,c.country,c.created_date,c.status FROM import_customers c JOIN(SELECT MIN(stg_row_id)m FROM import_customers GROUP BY customer_id)k ON k.m=c.stg_row_id;
-- equipment_units: dedup on equipment_id (75 duplicate rows in staging)
INSERT INTO equipment_units SELECT e.equipment_id,e.customer_id,e.model,e.serial_number,e.install_date,e.warranty_expiration,e.status,e.location_notes FROM import_equipment e JOIN(SELECT MIN(stg_row_id)m FROM import_equipment GROUP BY equipment_id)k ON k.m=e.stg_row_id;
-- quarantine orphan dispatches BEFORE loading service_logs
INSERT INTO rejected_dispatches SELECT d.stg_row_id,d.dispatch_id,d.equipment_id,d.customer_id,'orphan equipment_id',NOW() FROM import_dispatches d WHERE d.equipment_id NOT IN(SELECT equipment_id FROM equipment_units);
-- service_logs: no dedup (dispatch_id already unique); keep only rows with a real equipment_id
INSERT INTO service_logs SELECT d.dispatch_id,d.equipment_id,d.dispatch_date,d.technician,d.service_type,d.hours_spent,d.labor_cost,d.resolution_summary,d.status FROM import_dispatches d JOIN equipment_units u ON u.equipment_id=d.equipment_id;
-- parts_inventory: no dedup (part_id already unique)
INSERT INTO parts_inventory SELECT p.part_id,p.part_name,p.category,p.manufacturer,p.supplier,p.unit_cost,p.unit_price,p.stock_quantity,p.reorder_level FROM import_parts p;
-- warranty_claims: dedup on claim_id (48 duplicate rows); NULL dispatch_id/part_id pass through;
-- 13 claims point at quarantined (orphan) dispatches: keep the claim, NULL the dangling dispatch link
INSERT INTO warranty_claims SELECT w.claim_id,w.equipment_id,IF(w.dispatch_id IN(SELECT dispatch_id FROM service_logs),w.dispatch_id,NULL),w.part_id,w.claim_date,w.claim_amount,w.approved_amount,w.status,w.denial_reason,w.claim_notes FROM import_warranty_claims w JOIN(SELECT MIN(stg_row_id)m FROM import_warranty_claims GROUP BY claim_id)k ON k.m=w.stg_row_id;
-- row counts vs expected are checked in 06_validate.sql
