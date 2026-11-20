-- =============================================================================
-- Galera health check: run on any node
--   sudo mariadb < sql/cluster_status.sql
--
-- Healthy cluster: wsrep_cluster_size = 3, wsrep_cluster_status = Primary,
-- wsrep_local_state_comment = Synced, wsrep_ready = ON.
-- =============================================================================

SHOW STATUS WHERE Variable_name IN (
    'wsrep_cluster_size',
    'wsrep_cluster_status',
    'wsrep_ready',
    'wsrep_local_state_comment',
    'wsrep_connected',
    'wsrep_cluster_state_uuid',
    'wsrep_last_committed'
);

-- Which node am I, and who are my peers?
SELECT @@wsrep_node_name     AS node_name,
       @@wsrep_node_address  AS node_address,
       @@wsrep_cluster_name  AS cluster_name;

SHOW STATUS LIKE 'wsrep_incoming_addresses';
