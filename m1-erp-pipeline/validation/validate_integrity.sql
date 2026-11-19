-- =============================================================================
-- Silver layer integrity checks
-- -----------------------------------------------------------------------------
-- Each check returns one row: check_name, observed value, expected value and
-- PASS/FAIL. Run after the Silver tables are loaded:
--
--   mariadb gigavolt < m1-erp-pipeline/validation/validate_integrity.sql
--
-- Expected row counts are the reference values from the production load.
-- =============================================================================

USE gigavolt;

SELECT check_name, observed, expected,
       IF(observed = expected, 'PASS', 'FAIL') AS result
FROM (
    -- Row counts -------------------------------------------------------------
    SELECT 'rows: customers'        AS check_name, (SELECT COUNT(*) FROM customers)        AS observed, 500  AS expected
    UNION ALL SELECT 'rows: equipment',        (SELECT COUNT(*) FROM equipment),        2500
    UNION ALL SELECT 'rows: equipment_models', (SELECT COUNT(*) FROM equipment_models), 5
    UNION ALL SELECT 'rows: dispatches',       (SELECT COUNT(*) FROM dispatches),       4941
    UNION ALL SELECT 'rows: parts',            (SELECT COUNT(*) FROM parts),            150
    UNION ALL SELECT 'rows: warranty_claims',  (SELECT COUNT(*) FROM warranty_claims),  1200

    -- Orphaned foreign keys ---------------------------------------------------
    UNION ALL SELECT 'orphans: equipment -> customers',
        (SELECT COUNT(*) FROM equipment e
           LEFT JOIN customers c ON c.customer_id = e.customer_id
          WHERE c.customer_id IS NULL), 0
    UNION ALL SELECT 'orphans: equipment -> equipment_models',
        (SELECT COUNT(*) FROM equipment e
           LEFT JOIN equipment_models m ON m.model = e.model
          WHERE m.model IS NULL), 0
    UNION ALL SELECT 'orphans: dispatches -> equipment',
        (SELECT COUNT(*) FROM dispatches d
           LEFT JOIN equipment e ON e.equipment_id = d.equipment_id
          WHERE e.equipment_id IS NULL), 0
    UNION ALL SELECT 'orphans: warranty_claims -> equipment',
        (SELECT COUNT(*) FROM warranty_claims w
           LEFT JOIN equipment e ON e.equipment_id = w.equipment_id
          WHERE e.equipment_id IS NULL), 0
    UNION ALL SELECT 'orphans: warranty_claims -> dispatches',
        (SELECT COUNT(*) FROM warranty_claims w
           LEFT JOIN dispatches d ON d.dispatch_id = w.dispatch_id
          WHERE w.dispatch_id IS NOT NULL AND d.dispatch_id IS NULL), 0
    UNION ALL SELECT 'orphans: warranty_claims -> parts',
        (SELECT COUNT(*) FROM warranty_claims w
           LEFT JOIN parts p ON p.part_id = w.part_id
          WHERE w.part_id IS NOT NULL AND p.part_id IS NULL), 0

    -- Domain rules -----------------------------------------------------------
    UNION ALL SELECT 'rule: warranty expires after install',
        (SELECT COUNT(*) FROM equipment
          WHERE warranty_expiration < install_date), 0
    UNION ALL SELECT 'rule: non-negative labor cost and hours',
        (SELECT COUNT(*) FROM dispatches
          WHERE labor_cost < 0 OR hours_spent < 0), 0
    UNION ALL SELECT 'rule: non-negative stock and reorder level',
        (SELECT COUNT(*) FROM parts
          WHERE stock_quantity < 0 OR reorder_level < 0), 0
    UNION ALL SELECT 'rule: approved amount <= claim amount',
        (SELECT COUNT(*) FROM warranty_claims
          WHERE approved_amount > claim_amount), 0
    UNION ALL SELECT 'rule: no HTML left in resolution text',
        (SELECT COUNT(*) FROM dispatches
          WHERE resolution_summary REGEXP '<[^>]+>'), 0
    UNION ALL SELECT 'rule: no leading/trailing whitespace in technician',
        (SELECT COUNT(*) FROM dispatches
          WHERE technician <> TRIM(technician)), 0
    UNION ALL SELECT 'rule: no stray carriage returns (CRLF load defect)',
        (SELECT COUNT(*) FROM customers WHERE status LIKE CONCAT('%', CHAR(13), '%'))
      + (SELECT COUNT(*) FROM equipment WHERE location_notes LIKE CONCAT('%', CHAR(13), '%')), 0
    UNION ALL SELECT 'rule: zip codes are 5 digits',
        (SELECT COUNT(*) FROM customers WHERE zip NOT REGEXP '^[0-9]{5}$'), 0
) AS checks;
