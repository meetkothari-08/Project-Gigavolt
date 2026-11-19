-- 06_validate.sql: integrity evidence. Row counts vs expected (PASS/FAIL) and orphan FK counts (must all be 0).
-- Long-form checks (null violations, duplicate PKs, samples, reconciliation) live in docs/validation_queries.sql.
USE gigavolt_erp;
-- row counts vs expected
SELECT t,n,e,IF(n=e,'PASS','FAIL')r FROM(SELECT 'customers't,COUNT(*)n,500 e FROM customers
UNION ALL SELECT 'locations',COUNT(*),473 FROM locations
UNION ALL SELECT 'equipment_models',COUNT(*),5 FROM equipment_models
UNION ALL SELECT 'equipment_units',COUNT(*),2500 FROM equipment_units
UNION ALL SELECT 'service_logs',COUNT(*),4941 FROM service_logs
UNION ALL SELECT 'rejected_dispatches',COUNT(*),59 FROM rejected_dispatches
UNION ALL SELECT 'parts_inventory',COUNT(*),150 FROM parts_inventory
UNION ALL SELECT 'warranty_claims',COUNT(*),1200 FROM warranty_claims)x;
-- orphan FK rows per relationship (child>parent)
SELECT 'customers>locations'k,COUNT(*)orphans FROM customers WHERE zip NOT IN(SELECT zip FROM locations)
UNION ALL SELECT 'equipment_units>customers',COUNT(*) FROM equipment_units WHERE customer_id NOT IN(SELECT customer_id FROM customers)
UNION ALL SELECT 'equipment_units>models',COUNT(*) FROM equipment_units WHERE model NOT IN(SELECT model FROM equipment_models)
UNION ALL SELECT 'service_logs>equipment',COUNT(*) FROM service_logs WHERE equipment_id NOT IN(SELECT equipment_id FROM equipment_units)
UNION ALL SELECT 'warranty_claims>equipment',COUNT(*) FROM warranty_claims WHERE equipment_id NOT IN(SELECT equipment_id FROM equipment_units)
UNION ALL SELECT 'warranty_claims>service_logs',COUNT(*) FROM warranty_claims WHERE dispatch_id IS NOT NULL AND dispatch_id NOT IN(SELECT dispatch_id FROM service_logs)
UNION ALL SELECT 'warranty_claims>parts',COUNT(*) FROM warranty_claims WHERE part_id IS NOT NULL AND part_id NOT IN(SELECT part_id FROM parts_inventory);
