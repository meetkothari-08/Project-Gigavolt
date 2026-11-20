-- =============================================================================
-- Controlled single-node failover test
-- -----------------------------------------------------------------------------
-- Run each step on the node named in its heading. Recorded run: 2026-10-11.
--
--   Step 1  any node      create the test table and a baseline row
--   Step 2  gigavolt-1    sudo systemctl stop mariadb
--   Step 3  gigavolt-2    confirm a 2-node Primary component, write a row
--   Step 4  gigavolt-3    read the row written while node 1 was down
--   Step 5  gigavolt-1    sudo systemctl start mariadb   (join, NOT galera_new_cluster)
--   Step 6  gigavolt-1    confirm 3 / Primary / Synced and the row is present
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Step 1 (any node, cluster healthy): baseline
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gigavolt.failover_test (
    test_id    INT          NOT NULL PRIMARY KEY,   -- Galera requires a PK on replicated tables
    message    VARCHAR(255) NOT NULL,
    created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE = InnoDB;

INSERT IGNORE INTO gigavolt.failover_test (test_id, message)
VALUES (1, 'Baseline: all three nodes online');

-- -----------------------------------------------------------------------------
-- Step 3 (gigavolt-2, after node 1 is stopped)
-- -----------------------------------------------------------------------------
SHOW STATUS LIKE 'wsrep_cluster_size';          -- expect 2
SHOW STATUS LIKE 'wsrep_cluster_status';        -- expect Primary (2 of 3 = quorum)
SHOW STATUS LIKE 'wsrep_local_state_comment';   -- expect Synced
SHOW TABLES FROM gigavolt LIKE 'failover_test';

INSERT INTO gigavolt.failover_test (test_id, message)
VALUES (3, 'Failover test while Node 1 is down');

SELECT * FROM gigavolt.failover_test WHERE test_id = 3;

-- -----------------------------------------------------------------------------
-- Step 4 (gigavolt-3): the write made on node 2 has replicated
-- -----------------------------------------------------------------------------
SELECT * FROM gigavolt.failover_test WHERE test_id = 3;

-- -----------------------------------------------------------------------------
-- Step 6 (gigavolt-1, after `systemctl start mariadb`): rejoined and caught up
-- -----------------------------------------------------------------------------
SHOW STATUS LIKE 'wsrep_cluster_size';          -- expect 3
SHOW STATUS LIKE 'wsrep_cluster_status';        -- expect Primary
SHOW STATUS LIKE 'wsrep_local_state_comment';   -- expect Synced

SELECT * FROM gigavolt.failover_test
 WHERE message = 'Failover test while Node 1 is down';
