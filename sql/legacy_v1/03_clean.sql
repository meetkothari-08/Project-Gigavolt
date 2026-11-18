-- 03_clean.sql: cleanse import_* staging in place; SQL only; idempotent.
USE gigavolt_erp;
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
-- helpers: cx = tag/space/null-token scrub; nd = five-format date to ISO text
DROP FUNCTION IF EXISTS cx;
DROP FUNCTION IF EXISTS nd;
DELIMITER //
CREATE FUNCTION cx(t TEXT) RETURNS TEXT DETERMINISTIC
RETURN NULLIF(NULLIF(NULLIF(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(t,'<[^>]+>',''),' +',' ')),''),'NULL'),'N/A')//
CREATE FUNCTION nd(t TEXT) RETURNS TEXT DETERMINISTIC
BEGIN
DECLARE c TEXT;
SET c=REPLACE(cx(t),'/','-');
RETURN IF(c REGEXP '^[0-9]{2}-[0-9]{2}-[0-9]{4}$',CONCAT(RIGHT(c,4),'-',LEFT(c,5)),LEFT(c,10));
END//
DELIMITER ;
-- a+b+c+d: strip tags, collapse spaces, trim, null tokens, normalise dates (ids trimmed only)
UPDATE import_customers SET customer_id=TRIM(customer_id),company_name=cx(company_name),contact_name=cx(contact_name),phone=cx(phone),email=cx(email),address=cx(address),city=cx(city),state=cx(state),zip=cx(zip),country=cx(country),status=cx(status),created_date=nd(created_date);
UPDATE import_equipment SET equipment_id=TRIM(equipment_id),customer_id=TRIM(customer_id),model=cx(model),serial_number=cx(serial_number),capacity_kw=cx(capacity_kw),voltage=cx(voltage),status=cx(status),location_notes=cx(location_notes),install_date=nd(install_date),warranty_expiration=nd(warranty_expiration);
UPDATE import_dispatches SET dispatch_id=TRIM(dispatch_id),equipment_id=TRIM(equipment_id),customer_id=TRIM(customer_id),technician=cx(technician),service_type=cx(service_type),hours_spent=cx(hours_spent),labor_cost=cx(labor_cost),resolution_summary=cx(resolution_summary),status=cx(status),dispatch_date=nd(dispatch_date);
UPDATE import_parts SET part_id=TRIM(part_id),part_name=cx(part_name),category=cx(category),manufacturer=cx(manufacturer),supplier=cx(supplier),unit_cost=cx(unit_cost),unit_price=cx(unit_price),stock_quantity=cx(stock_quantity),reorder_level=cx(reorder_level);
UPDATE import_warranty_claims SET claim_id=TRIM(claim_id),equipment_id=TRIM(equipment_id),dispatch_id=cx(dispatch_id),part_id=cx(part_id),claim_amount=cx(claim_amount),approved_amount=cx(approved_amount),status=cx(status),denial_reason=cx(denial_reason),claim_notes=cx(claim_notes),claim_date=nd(claim_date);
-- e: phones to (NNN) NNN-NNNN
UPDATE import_customers SET phone=REGEXP_REPLACE(phone,'[^0-9]','');
UPDATE import_customers SET phone=SUBSTRING(phone,2) WHERE phone REGEXP '^1[0-9]{10}$';
UPDATE import_customers SET phone=CONCAT('(',SUBSTRING(phone,1,3),') ',SUBSTRING(phone,4,3),'-',SUBSTRING(phone,7,4)) WHERE phone REGEXP '^[0-9]{10}$';
-- f: money to bare decimal
UPDATE import_dispatches SET labor_cost=REGEXP_REPLACE(labor_cost,'[^0-9.]','');
-- g: canonical status casing (ci collation matches any case), lowercase email
UPDATE import_customers SET status=CASE status WHEN 'active' THEN 'Active' WHEN 'inactive' THEN 'Inactive' WHEN 'pending' THEN 'Pending' ELSE status END;
UPDATE import_equipment SET status=CASE status WHEN 'in service' THEN 'In Service' WHEN 'maintenance' THEN 'Maintenance' WHEN 'standby' THEN 'Standby' WHEN 'decommissioned' THEN 'Decommissioned' ELSE status END;
UPDATE import_dispatches SET status=CASE status WHEN 'completed' THEN 'Completed' WHEN 'pending' THEN 'Pending' WHEN 'cancelled' THEN 'Cancelled' WHEN 'in progress' THEN 'In Progress' ELSE status END;
UPDATE import_warranty_claims SET status=CASE status WHEN 'approved' THEN 'Approved' WHEN 'pending' THEN 'Pending' WHEN 'under review' THEN 'Under Review' WHEN 'rejected' THEN 'Rejected' ELSE status END;
UPDATE import_customers SET email=LOWER(email);
-- h: single-market country, zip leading zeros, numeric voltage
UPDATE import_customers SET country='US',zip=LPAD(zip,5,'0');
UPDATE import_equipment SET voltage=REGEXP_REPLACE(voltage,'[^0-9]','');
-- verification: every count must be 0 (nonstd_phones counts non-10-digit source values)
SELECT (SELECT COUNT(*) FROM import_dispatches WHERE resolution_summary REGEXP '<[^>]+>' OR dispatch_date NOT REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' OR labor_cost REGEXP '[^0-9.]')bad_dispatch_rows,(SELECT COUNT(*) FROM import_customers WHERE LENGTH(phone)<>14)nonstd_phones,(SELECT COUNT(*) FROM import_equipment WHERE voltage REGEXP '[^0-9]')bad_voltage;
