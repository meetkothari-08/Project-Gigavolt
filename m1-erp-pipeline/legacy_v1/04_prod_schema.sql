-- 04_prod_schema.sql: Silver / 3NF production layer.
-- ENGINE=InnoDB on every table (real types, PKs, FKs; MyISAM would silently ignore the FKs).
-- Charset + collation are inherited from the gigavolt_erp database (utf8mb4 / utf8mb4_unicode_ci,
-- set in 01_staging_schema.sql), so no per-table "DEFAULT CHARSET" clause is needed.
-- FKs use the "FOREIGN KEY <name> (col)" form so each constraint is still explicitly named.
-- Idempotent: children dropped before parents, parents created before children.
USE gigavolt_erp;
DROP TABLE IF EXISTS rejected_dispatches,warranty_claims,parts_inventory,service_logs,equipment_units,customers,equipment_models,locations;
-- locations: zip -> (city,state), 3NF split out of customers
CREATE TABLE locations(zip CHAR(5)PRIMARY KEY,city VARCHAR(100)NOT NULL,state CHAR(2)NOT NULL)ENGINE=InnoDB;
-- equipment_models: model -> (capacity_kw,voltage), 3NF split out of equipment
CREATE TABLE equipment_models(model VARCHAR(20)PRIMARY KEY,capacity_kw INT NOT NULL,voltage INT NOT NULL)ENGINE=InnoDB;
-- customers: one row per real customer; zip resolves through locations
CREATE TABLE customers(customer_id VARCHAR(10)PRIMARY KEY,company_name VARCHAR(150)NOT NULL,contact_name VARCHAR(100),phone VARCHAR(20),email VARCHAR(150),address VARCHAR(200),zip CHAR(5)NOT NULL,country CHAR(2)NOT NULL,created_date DATE,status ENUM('Active','Inactive','Pending')NOT NULL,FOREIGN KEY fk_cust_loc(zip)REFERENCES locations(zip))ENGINE=InnoDB;
-- equipment_units: installed units, one owner each, typed by equipment_models
CREATE TABLE equipment_units(equipment_id VARCHAR(10)PRIMARY KEY,customer_id VARCHAR(10)NOT NULL,model VARCHAR(20)NOT NULL,serial_number VARCHAR(30),install_date DATE,warranty_expiration DATE,status ENUM('In Service','Maintenance','Standby','Decommissioned')NOT NULL,location_notes VARCHAR(255),FOREIGN KEY fk_eu_cust(customer_id)REFERENCES customers(customer_id),FOREIGN KEY fk_eu_model(model)REFERENCES equipment_models(model))ENGINE=InnoDB;
-- service_logs: dispatches; no customer_id, derivable via equipment_units.customer_id
CREATE TABLE service_logs(dispatch_id VARCHAR(12)PRIMARY KEY,equipment_id VARCHAR(10)NOT NULL,dispatch_date DATE,technician VARCHAR(100),service_type VARCHAR(40),hours_spent DEC(5,1),labor_cost DEC(10,2),resolution_summary TEXT,status ENUM('Completed','Pending','Cancelled','In Progress')NOT NULL,FOREIGN KEY fk_sl_eu(equipment_id)REFERENCES equipment_units(equipment_id))ENGINE=InnoDB;
-- parts_inventory: parts catalog and stock levels
CREATE TABLE parts_inventory(part_id VARCHAR(10)PRIMARY KEY,part_name VARCHAR(100)NOT NULL,category VARCHAR(40),manufacturer VARCHAR(60),supplier VARCHAR(30),unit_cost DEC(10,2),unit_price DEC(10,2),stock_quantity INT,reorder_level INT)ENGINE=InnoDB;
-- warranty_claims: dispatch_id and part_id are legitimately nullable FKs
CREATE TABLE warranty_claims(claim_id VARCHAR(10)PRIMARY KEY,equipment_id VARCHAR(10)NOT NULL,dispatch_id VARCHAR(12),part_id VARCHAR(10),claim_date DATE,claim_amount DEC(10,2),approved_amount DEC(10,2),status ENUM('Approved','Pending','Under Review','Rejected')NOT NULL,denial_reason VARCHAR(255),claim_notes TEXT,FOREIGN KEY fk_wc_eu(equipment_id)REFERENCES equipment_units(equipment_id),FOREIGN KEY fk_wc_sl(dispatch_id)REFERENCES service_logs(dispatch_id),FOREIGN KEY fk_wc_part(part_id)REFERENCES parts_inventory(part_id))ENGINE=InnoDB;
-- rejected_dispatches: quarantine for dispatch rows with no equipment_units match
CREATE TABLE rejected_dispatches(stg_row_id INT PRIMARY KEY,dispatch_id VARCHAR(12),equipment_id VARCHAR(10),customer_id VARCHAR(10),reject_reason VARCHAR(100)NOT NULL,rejected_at TIMESTAMP NOT NULL DEFAULT NOW())ENGINE=InnoDB;
