-- =============================================================================
-- Silver layer: cleaned, normalized (3NF) ERP tables
-- -----------------------------------------------------------------------------
--   customers 1──* equipment *──1 equipment_models
--                     │
--                     1
--                     *
--                 dispatches 1──* warranty_claims *──1 parts
--                     (warranty_claims also references equipment)
--
-- Model attributes (capacity_kw, voltage) were moved out of `equipment` into
-- `equipment_models` to remove a transitive dependency
-- (equipment_id -> model -> capacity_kw/voltage).
--
-- Column-level collations match the production schema exactly so that the
-- foreign keys between tables loaded at different times stay compatible.
-- =============================================================================

USE gigavolt;

CREATE TABLE IF NOT EXISTS customers (
    customer_id   VARCHAR(50)  NOT NULL,
    company_name  VARCHAR(255) NOT NULL,
    contact_name  VARCHAR(255) NOT NULL,
    phone         VARCHAR(20)  NOT NULL,
    email         VARCHAR(255) NOT NULL,
    address       VARCHAR(500) NOT NULL,
    city          VARCHAR(100) NOT NULL,
    state         VARCHAR(10)  NOT NULL,
    zip           VARCHAR(20)  NOT NULL,
    country       VARCHAR(100) DEFAULT NULL,
    created_date  DATE         NOT NULL,
    status        VARCHAR(50)  NOT NULL,
    PRIMARY KEY (customer_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS equipment_models (
    model        VARCHAR(100)  NOT NULL,
    capacity_kw  DECIMAL(10,2) NOT NULL,
    voltage      VARCHAR(50)   NOT NULL,
    PRIMARY KEY (model)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_uca1400_ai_ci;

CREATE TABLE IF NOT EXISTS equipment (
    equipment_id         VARCHAR(50)  NOT NULL,
    customer_id          VARCHAR(50)  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    model                VARCHAR(100) NOT NULL,
    serial_number        VARCHAR(100) DEFAULT NULL,
    install_date         DATE         NOT NULL,
    warranty_expiration  DATE         NOT NULL,
    status               VARCHAR(50)  NOT NULL,
    location_notes       TEXT         DEFAULT NULL,
    PRIMARY KEY (equipment_id),
    KEY idx_equipment_customer (customer_id),
    KEY fk_equipment_model (model),
    CONSTRAINT fk_equipment_customer
        FOREIGN KEY (customer_id) REFERENCES customers (customer_id),
    CONSTRAINT fk_equipment_model
        FOREIGN KEY (model) REFERENCES equipment_models (model)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_uca1400_ai_ci;

CREATE TABLE IF NOT EXISTS dispatches (
    dispatch_id         VARCHAR(50)   NOT NULL,
    equipment_id        VARCHAR(50)   NOT NULL,
    dispatch_date       DATE          NOT NULL,
    technician          VARCHAR(255)  DEFAULT NULL,
    service_type        VARCHAR(100)  NOT NULL,
    hours_spent         DECIMAL(10,2) NOT NULL,
    labor_cost          DECIMAL(10,2) NOT NULL,
    resolution_summary  TEXT          DEFAULT NULL,
    status              VARCHAR(50)   NOT NULL,
    PRIMARY KEY (dispatch_id),
    KEY fk_dispatches_equipment (equipment_id),
    CONSTRAINT fk_dispatches_equipment
        FOREIGN KEY (equipment_id) REFERENCES equipment (equipment_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_uca1400_ai_ci;

CREATE TABLE IF NOT EXISTS parts (
    part_id         VARCHAR(50)   NOT NULL,
    part_name       VARCHAR(255)  NOT NULL,
    category        VARCHAR(100)  NOT NULL,
    manufacturer    VARCHAR(100)  NOT NULL,
    supplier        VARCHAR(100)  NOT NULL,
    unit_cost       DECIMAL(10,2) NOT NULL,
    unit_price      DECIMAL(10,2) NOT NULL,
    stock_quantity  INT           NOT NULL,
    reorder_level   INT           NOT NULL,
    PRIMARY KEY (part_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS warranty_claims (
    claim_id         VARCHAR(50)   NOT NULL,
    equipment_id     VARCHAR(50)   CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci NOT NULL,
    dispatch_id      VARCHAR(50)   CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci DEFAULT NULL,
    part_id          VARCHAR(50)   DEFAULT NULL,
    claim_date       DATE          NOT NULL,
    claim_amount     DECIMAL(10,2) NOT NULL,
    approved_amount  DECIMAL(10,2) DEFAULT NULL,
    status           VARCHAR(50)   NOT NULL,
    denial_reason    TEXT          DEFAULT NULL,
    claim_notes      TEXT          DEFAULT NULL,
    PRIMARY KEY (claim_id),
    KEY fk_warranty_claim_equipment (equipment_id),
    KEY fk_warranty_claim_dispatch (dispatch_id),
    KEY fk_warranty_claim_part (part_id),
    CONSTRAINT fk_warranty_claim_dispatch
        FOREIGN KEY (dispatch_id) REFERENCES dispatches (dispatch_id),
    CONSTRAINT fk_warranty_claim_equipment
        FOREIGN KEY (equipment_id) REFERENCES equipment (equipment_id),
    CONSTRAINT fk_warranty_claim_part
        FOREIGN KEY (part_id) REFERENCES parts (part_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
