-- =============================================================================
-- Bronze layer: raw landing tables
-- -----------------------------------------------------------------------------
-- One table per source CSV. Every column is loaded as text so that malformed
-- dates, currency strings ("$1,250.00"), HTML fragments and duplicate IDs are
-- preserved exactly as received. `bronze_row_id` gives each raw row a stable
-- lineage key that is carried into the Silver staging and quarantine tables.
-- =============================================================================

USE gigavolt;

CREATE TABLE IF NOT EXISTS bronze_customers (
    bronze_row_id  INT          NOT NULL AUTO_INCREMENT,
    customer_id    VARCHAR(50)  DEFAULT NULL,
    company_name   VARCHAR(255) DEFAULT NULL,
    contact_name   VARCHAR(255) DEFAULT NULL,
    phone          VARCHAR(100) DEFAULT NULL,
    email          VARCHAR(255) DEFAULT NULL,
    address        VARCHAR(500) DEFAULT NULL,
    city           VARCHAR(100) DEFAULT NULL,
    state          VARCHAR(100) DEFAULT NULL,
    zip            VARCHAR(20)  DEFAULT NULL,
    country        VARCHAR(100) DEFAULT NULL,
    created_date   VARCHAR(100) DEFAULT NULL,
    status         VARCHAR(50)  DEFAULT NULL,
    PRIMARY KEY (bronze_row_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_uca1400_ai_ci;

CREATE TABLE IF NOT EXISTS bronze_equipment (
    bronze_row_id        INT          NOT NULL AUTO_INCREMENT,
    equipment_id         VARCHAR(50)  DEFAULT NULL,
    customer_id          VARCHAR(50)  DEFAULT NULL,
    model                VARCHAR(100) DEFAULT NULL,
    serial_number        VARCHAR(100) DEFAULT NULL,
    install_date         VARCHAR(100) DEFAULT NULL,
    capacity_kw          VARCHAR(50)  DEFAULT NULL,
    voltage              VARCHAR(50)  DEFAULT NULL,
    warranty_expiration  VARCHAR(100) DEFAULT NULL,
    status               VARCHAR(50)  DEFAULT NULL,
    location_notes       TEXT         DEFAULT NULL,
    PRIMARY KEY (bronze_row_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bronze_dispatches (
    bronze_row_id       INT          NOT NULL AUTO_INCREMENT,
    dispatch_id         VARCHAR(50)  DEFAULT NULL,
    equipment_id        VARCHAR(50)  DEFAULT NULL,
    customer_id         VARCHAR(50)  DEFAULT NULL,
    dispatch_date       VARCHAR(100) DEFAULT NULL,
    technician          VARCHAR(255) DEFAULT NULL,
    service_type        VARCHAR(100) DEFAULT NULL,
    hours_spent         VARCHAR(50)  DEFAULT NULL,
    labor_cost          VARCHAR(100) DEFAULT NULL,
    resolution_summary  TEXT         DEFAULT NULL,
    status              VARCHAR(50)  DEFAULT NULL,
    PRIMARY KEY (bronze_row_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bronze_parts (
    bronze_row_id   INT          NOT NULL AUTO_INCREMENT,
    part_id         VARCHAR(50)  DEFAULT NULL,
    part_name       TEXT         DEFAULT NULL,
    category        VARCHAR(100) DEFAULT NULL,
    manufacturer    VARCHAR(100) DEFAULT NULL,
    supplier        VARCHAR(100) DEFAULT NULL,
    unit_cost       VARCHAR(50)  DEFAULT NULL,
    unit_price      VARCHAR(50)  DEFAULT NULL,
    stock_quantity  VARCHAR(50)  DEFAULT NULL,
    reorder_level   VARCHAR(50)  DEFAULT NULL,
    PRIMARY KEY (bronze_row_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_uca1400_ai_ci;

CREATE TABLE IF NOT EXISTS bronze_warranty_claims (
    bronze_row_id    INT          NOT NULL AUTO_INCREMENT,
    claim_id         VARCHAR(50)  DEFAULT NULL,
    equipment_id     VARCHAR(50)  DEFAULT NULL,
    dispatch_id      VARCHAR(50)  DEFAULT NULL,
    part_id          VARCHAR(50)  DEFAULT NULL,
    claim_date       VARCHAR(100) DEFAULT NULL,
    claim_amount     VARCHAR(50)  DEFAULT NULL,
    approved_amount  VARCHAR(50)  DEFAULT NULL,
    status           VARCHAR(50)  DEFAULT NULL,
    denial_reason    TEXT         DEFAULT NULL,
    claim_notes      TEXT         DEFAULT NULL,
    PRIMARY KEY (bronze_row_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_uca1400_ai_ci;
