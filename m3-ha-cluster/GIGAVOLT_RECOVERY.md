# Gigavolt Galera recovery runbook

How to bring the three-node cluster back after AWS Learner Lab stops the instances. Each node has `Restart=no` ([`config/mariadb-no-autorestart.conf`](config/mariadb-no-autorestart.conf)), so nothing starts by itself: you choose which node bootstraps.

> **The one rule:** only the node holding the most recent committed transaction may run `galera_new_cluster`. Bootstrapping any other node starts a new history and discards the writes the others had.

## 1. Inspect every node

On **each** node:

```bash
sudo m3-ha-cluster/scripts/gigavolt-galera-recovery.sh
```

It reports whether MariaDB is running, the live `wsrep_*` status if it is, and the saved state in `/var/lib/mysql/grastate.dat`:

```
uuid:    9ba5051b-e515-11f1-b080-d6e3434d2bb8
seqno:   130
safe_to_bootstrap: 1
```

| What you see | Meaning |
|---|---|
| A node is running and reports `Primary` | The cluster is still up. Do **not** bootstrap; start the other nodes normally (step 4). |
| `safe_to_bootstrap: 1` | This node shut down last, cleanly. It is the bootstrap node. |
| `seqno: N` with `safe_to_bootstrap: 0` | Clean stop at transaction N. Compare N across nodes. |
| `seqno: -1` (server stopped) | Unclean stop (crash or power loss): the position is unknown. Recover it first (step 2). |

## 2. Recover unknown positions

On every stopped node that shows `seqno: -1`:

```bash
sudo -u mysql mariadbd --wsrep-recover
sudo grep 'Recovered position' /var/log/mysql/error.log | tail -1
#   WSREP: Recovered position: 9ba5051b-e515-11f1-b080-d6e3434d2bb8:135
```

The number after the colon is that node's last committed seqno.

## 3. Choose the bootstrap node

From an admin host that can SSH to the nodes:

```bash
m3-ha-cluster/scripts/select_bootstrap_node.sh --ssh gigavolt-1 gigavolt-2 gigavolt-3 \
    --recovered gigavolt-2=135 --recovered gigavolt-3=135
```

```
NODE           UUID                                      SEQNO  RECOVERED SAFE_TO_BOOTSTRAP
gigavolt-1     9ba5051b-e515-11f1-b080-d6e3434d2bb8        133          - 0
gigavolt-2     9ba5051b-e515-11f1-b080-d6e3434d2bb8         -1        135 0
gigavolt-3     9ba5051b-e515-11f1-b080-d6e3434d2bb8         -1        135 0

BOOTSTRAP: gigavolt-2 (highest committed seqno: 135)
```

It refuses (exit code 2) when the nodes report different cluster UUIDs or when a position is still unknown. In this example gigavolt-1 has a valid-looking seqno of 133 but is **behind**: bootstrapping it would lose two transactions.

## 4. Bootstrap, then join one node at a time

```bash
# On the chosen node only. If it is not already marked safe:
sudo sed -i 's/^safe_to_bootstrap: 0/safe_to_bootstrap: 1/' /var/lib/mysql/grastate.dat
sudo galera_new_cluster

# Then, one at a time on the other nodes (they catch up through IST/SST):
sudo systemctl start mariadb
```

## 5. Verify

```bash
sudo mariadb < m3-ha-cluster/sql/cluster_status.sql        # on any node
mariadb -h <node> gigavolt < m3-ha-cluster/sql/replication_check.sql   # on each node
```

Expect `wsrep_cluster_size = 3`, `Primary`, `Synced`, `wsrep_ready = ON`, and identical row counts on every node (dispatches = 4,941).

## Single node failed, cluster still running

Do not bootstrap. On the failed node run `sudo systemctl start mariadb`. It joins the existing primary component and catches up. This is exactly what the [failover test](sql/failover_test.sql) did.

## Rehearse without AWS

[`local-test/rehearse.sh`](local-test/rehearse.sh) runs all of the above, including the stale-node case, on a local 3-node cluster.
