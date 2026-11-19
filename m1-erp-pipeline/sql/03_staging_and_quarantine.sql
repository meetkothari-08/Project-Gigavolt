-- =============================================================================
-- Silver staging and quarantine tables
-- -----------------------------------------------------------------------------
-- Staging tables hold typed, cleansed rows (dates parsed, currency stripped,
-- HTML removed, whitespace/casing normalized) before deduplication and the
-- final insert into the Silver tables. Each row keeps its `bronze_row_id`.
--
-- Rows that cannot satisfy referential integrity (for example a dispatch that
-- points at an equipment_id that does not exist) are written to a quarantine
-- table with a reason instead of being silently dropped.
-- =============================================================================

USE gigavolt;

CREATE TABLE IF NOT EXISTS silver_customers_staging (
    bronze_row_id  INT          DEFAULT NULL,
    customer_id    VARCHAR(50)  DEFAULT NULL,
    company_name   VARCHAR(255) DEFAULT NULL,
    contact_name   VARCHAR(255) DEFAULT NULL,
    phone          VARCHAR(20)  DEFAULT NULL,
    email          VARCHAR(255) DEFAULT NULL,
    address        VARCHAR(500) DEFAULT NULL,
    city           VARCHAR(100) DEFAULT NULL,
    state          VARCHAR(10)  DEFAULT NULL,
    zip            VARCHAR(20)  DEFAULT NULL,
    country        VARCHAR(100) DEFAULT NULL,
    created_date   DATE         DEFAULT NULL,
    status         VARCHAR(50)  DEFAULT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS silver_equipment_staging (
    bronze_row_id        INT           DEFAULT NULL,
    equipment_id         VARCHAR(50)   DEFAULT NULL,
    customer_id          VARCHAR(50)   DEFAULT NULL,
    model                VARCHAR(100)  DEFAULT NULL,
    serial_number        VARCHAR(100)  DEFAULT NULL,
    install_date         DATE          DEFAULT NULL,
    capacity_kw          DECIMAL(10,2) DEFAULT NULL,
    voltage              VARCHAR(50)   DEFAULT NULL,
    warranty_expiration  DATE          DEFAULT NULL,
    status               VARCHAR(50)   DEFAULT NULL,
    location_notes       TEXT          DEFAULT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

-- Snapshot taken before duplicate equipment IDs were resolved, kept for audit.
CREATE TABLE IF NOT EXISTS silver_equipment_before_dedup (
    bronze_row_id        INT           DEFAULT NULL,
    equipment_id         VARCHAR(50)   DEFAULT NULL,
    customer_id          VARCHAR(50)   DEFAULT NULL,
    model                VARCHAR(100)  DEFAULT NULL,
    serial_number        VARCHAR(100)  DEFAULT NULL,
    install_date         DATE          DEFAULT NULL,
    capacity_kw          DECIMAL(10,2) DEFAULT NULL,
    voltage              VARCHAR(50)   DEFAULT NULL,
    warranty_expiration  DATE          DEFAULT NULL,
    status               VARCHAR(50)   DEFAULT NULL,
    location_notes       TEXT          DEFAULT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_uca1400_ai_ci;

CREATE TABLE IF NOT EXISTS silver_dispatches_staging (
    bronze_row_id       INT           DEFAULT NULL,
    dispatch_id         VARCHAR(50)   DEFAULT NULL,
    equipment_id        VARCHAR(50)   DEFAULT NULL,
    customer_id         VARCHAR(50)   DEFAULT NULL,
    dispatch_date       DATE          DEFAULT NULL,
    technician          VARCHAR(255)  DEFAULT NULL,
    service_type        VARCHAR(100)  DEFAULT NULL,
    hours_spent         DECIMAL(10,2) DEFAULT NULL,
    labor_cost          DECIMAL(10,2) DEFAULT NULL,
    resolution_summary  TEXT          DEFAULT NULL,
    status              VARCHAR(50)   DEFAULT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_uca1400_ai_ci;

CREATE TABLE IF NOT EXISTS silver_parts_staging (
    bronze_row_id   INT           DEFAULT NULL,
    part_id         VARCHAR(50)   DEFAULT NULL,
    part_name       VARCHAR(255)  DEFAULT NULL,
    category        VARCHAR(100)  DEFAULT NULL,
    manufacturer    VARCHAR(100)  DEFAULT NULL,
    supplier        VARCHAR(100)  DEFAULT NULL,
    unit_cost       DECIMAL(10,2) DEFAULT NULL,
    unit_price      DECIMAL(10,2) DEFAULT NULL,
    stock_quantity  INT           DEFAULT NULL,
    reorder_level   INT           DEFAULT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS silver_warranty_claims_staging (
    bronze_row_id    INT           NOT NULL,
    claim_id         VARCHAR(50)   DEFAULT NULL,
    equipment_id     VARCHAR(50)   CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci DEFAULT NULL,
    dispatch_id      VARCHAR(50)   CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci DEFAULT NULL,
    part_id          VARCHAR(50)   DEFAULT NULL,
    claim_date       DATE          DEFAULT NULL,
    claim_amount     DECIMAL(10,2) DEFAULT NULL,
    approved_amount  DECIMAL(10,2) DEFAULT NULL,
    status           VARCHAR(50)   DEFAULT NULL,
    denial_reason    TEXT          DEFAULT NULL,
    claim_notes      TEXT          DEFAULT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS dispatches_quarantine (
    bronze_row_id       INT           DEFAULT NULL,
    dispatch_id         VARCHAR(50)   DEFAULT NULL,
    equipment_id        VARCHAR(50)   DEFAULT NULL,
    customer_id         VARCHAR(50)   DEFAULT NULL,
    dispatch_date       DATE          DEFAULT NULL,
    technician          VARCHAR(255)  DEFAULT NULL,
    service_type        VARCHAR(100)  DEFAULT NULL,
    hours_spent         DECIMAL(10,2) DEFAULT NULL,
    labor_cost          DECIMAL(10,2) DEFAULT NULL,
    resolution_summary  TEXT          DEFAULT NULL,
    status              VARCHAR(50)   DEFAULT NULL,
    quarantine_reason   VARCHAR(255)  DEFAULT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_uca1400_ai_ci;

CREATE TABLE IF NOT EXISTS warranty_claims_quarantine (
    bronze_row_id      INT          NOT NULL,
    claim_id           VARCHAR(50)  DEFAULT NULL,
    equipment_id       VARCHAR(50)  CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci DEFAULT NULL,
    dispatch_id        VARCHAR(50)  CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci DEFAULT NULL,
    part_id            VARCHAR(50)  DEFAULT NULL,
    quarantine_reason  VARCHAR(255) NOT NULL,
    quarantined_at     TIMESTAMP    NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
