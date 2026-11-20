-- =============================================================================
-- Row store vs column store: analytical benchmark (run on gigavolt-3)
-- -----------------------------------------------------------------------------
-- Builds the same 494,100-row analytical dataset twice, once in InnoDB and
-- once in ColumnStore, then runs one grouped aggregation against each with
-- query profiling on.
--
-- Dataset: every Silver dispatch (4,941) joined to its equipment model and the
-- total warranty-claim amount filed against it, replicated 100x so the scan is
-- large enough for the storage engines to differ. The operational
-- gigavolt.dispatches table is not touched.
--
-- Galera only replicates InnoDB and only gigavolt-3 has the ColumnStore engine,
-- so this session runs with wsrep_on = OFF: the analytical tables stay local
-- to node 3 and the other nodes never receive ColumnStore DDL.
--
--   sudo mariadb < sql/columnstore_analytics.sql
--   (or load ColumnStore in batches with scripts/load_columnstore.sh)
-- =============================================================================

SET SESSION wsrep_on = OFF;
USE gigavolt;

-- -----------------------------------------------------------------------------
-- 1. Base rows: one per dispatch (4,941)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS analytics_base;
CREATE TABLE analytics_base ENGINE = InnoDB AS
SELECT
    d.dispatch_id,
    d.equipment_id,
    e.model,
    d.service_type,
    d.dispatch_date,
    d.hours_spent,
    d.labor_cost,
    COALESCE(w.claim_total, 0) AS total_claim_amount
FROM dispatches d
JOIN equipment e ON e.equipment_id = d.equipment_id
LEFT JOIN (
    SELECT dispatch_id, SUM(claim_amount) AS claim_total
    FROM warranty_claims
    WHERE dispatch_id IS NOT NULL
    GROUP BY dispatch_id
) w ON w.dispatch_id = d.dispatch_id;

-- -----------------------------------------------------------------------------
-- 2. Analytical tables, identical columns, different storage engines
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS analytics_innodb;
CREATE TABLE analytics_innodb (
    copy_no            SMALLINT      NOT NULL,
    dispatch_id        VARCHAR(50)   NOT NULL,
    equipment_id       VARCHAR(50)   NOT NULL,
    model              VARCHAR(100)  NOT NULL,
    service_type       VARCHAR(100)  NOT NULL,
    dispatch_date      DATE          NOT NULL,
    hours_spent        DECIMAL(10,2) NOT NULL,
    labor_cost         DECIMAL(10,2) NOT NULL,
    total_claim_amount DECIMAL(12,2) NOT NULL,
    PRIMARY KEY (copy_no, dispatch_id)
) ENGINE = InnoDB;

-- ColumnStore has no primary keys or secondary indexes: it stores each
-- column separately, compressed, and scans only the columns a query uses.
DROP TABLE IF EXISTS analytics_columnstore;
CREATE TABLE analytics_columnstore (
    copy_no            SMALLINT      NOT NULL,
    dispatch_id        VARCHAR(50)   NOT NULL,
    equipment_id       VARCHAR(50)   NOT NULL,
    model              VARCHAR(100)  NOT NULL,
    service_type       VARCHAR(100)  NOT NULL,
    dispatch_date      DATE          NOT NULL,
    hours_spent        DECIMAL(10,2) NOT NULL,
    labor_cost         DECIMAL(10,2) NOT NULL,
    total_claim_amount DECIMAL(12,2) NOT NULL
) ENGINE = ColumnStore;

-- -----------------------------------------------------------------------------
-- 3. Load 100 copies (494,100 rows) using the SEQUENCE engine as a row generator
-- -----------------------------------------------------------------------------
INSERT INTO analytics_innodb
SELECT s.seq, b.dispatch_id, b.equipment_id, b.model, b.service_type,
       b.dispatch_date, b.hours_spent, b.labor_cost, b.total_claim_amount
FROM seq_1_to_100 s CROSS JOIN analytics_base b;

INSERT INTO analytics_columnstore
SELECT * FROM analytics_innodb;

SELECT 'gigavolt.dispatches' AS table_name, 'InnoDB' AS engine, COUNT(*) AS row_count FROM dispatches
UNION ALL SELECT 'analytics_innodb',      'InnoDB',      COUNT(*) FROM analytics_innodb
UNION ALL SELECT 'analytics_columnstore', 'ColumnStore', COUNT(*) FROM analytics_columnstore;

-- -----------------------------------------------------------------------------
-- 4. Benchmark: the same aggregation against both engines, profiled
-- -----------------------------------------------------------------------------
SET profiling = 1;
SET profiling_history_size = 10;

SELECT
    model,
    COUNT(*) AS dispatches,
    ROUND(SUM(labor_cost), 2) AS total_labor_cost,
    ROUND(AVG(hours_spent), 2) AS avg_hours,
    ROUND(SUM(total_claim_amount), 2) AS total_claim_amount
FROM gigavolt.analytics_innodb
GROUP BY model
ORDER BY model;

SELECT
    model,
    COUNT(*) AS dispatches,
    ROUND(SUM(labor_cost), 2) AS total_labor_cost,
    ROUND(AVG(hours_spent), 2) AS avg_hours,
    ROUND(SUM(total_claim_amount), 2) AS total_claim_amount
FROM gigavolt.analytics_columnstore
GROUP BY model
ORDER BY model;

SHOW PROFILES;
