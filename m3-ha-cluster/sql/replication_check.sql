-- =============================================================================
-- Replication check: run on each node; every node must return the same counts
--   for n in gigavolt-1 gigavolt-2 gigavolt-3; do
--       mariadb -h "$n" -u <admin> -p gigavolt < sql/replication_check.sql
--   done
--
-- Recorded result (Milestone 3): dispatches = 4,941 on all three nodes.
-- =============================================================================

USE gigavolt;

SELECT @@wsrep_node_name AS node, t.table_name, t.row_count
FROM (
    SELECT 'customers'        AS table_name, COUNT(*) AS row_count FROM customers
    UNION ALL SELECT 'equipment',        COUNT(*) FROM equipment
    UNION ALL SELECT 'equipment_models', COUNT(*) FROM equipment_models
    UNION ALL SELECT 'dispatches',       COUNT(*) FROM dispatches
    UNION ALL SELECT 'parts',            COUNT(*) FROM parts
    UNION ALL SELECT 'warranty_claims',  COUNT(*) FROM warranty_claims
) AS t;

-- The Milestone 2 objects travel with the data (DDL replicates through Galera).
SELECT @@wsrep_node_name AS node,
       (SELECT COUNT(*) FROM information_schema.ROUTINES
         WHERE ROUTINE_SCHEMA = 'gigavolt' AND ROUTINE_NAME = 'sp_Prepare_RAG_Payloads') AS rag_procedure,
       (SELECT COUNT(*) FROM information_schema.TRIGGERS
         WHERE TRIGGER_SCHEMA = 'gigavolt') AS triggers,
       (SELECT COUNT(*) FROM information_schema.VIEWS
         WHERE TABLE_SCHEMA = 'gigavolt' AND TABLE_NAME = 'vw_Customer_Safe') AS masked_view;
