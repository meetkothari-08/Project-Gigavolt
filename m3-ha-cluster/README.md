# Milestone 3 · High-Availability Galera Cluster & ColumnStore Analytics

The Silver database moves from one MariaDB instance to a **three-node Galera cluster** on AWS EC2, with persistent EBS storage, a manual bootstrap protocol for the Learner Lab's forced shutdowns, a controlled failover test, and a **ColumnStore** engine on node 3 for analytical queries.

| | |
|---|---|
| **Cluster** | 3 × EC2 nodes · synchronous (certification-based) replication · EBS data volumes |
| **Failover** | Writes continued through a single-node outage; the failed node rejoined and resynced |
| **Recovery** | Manual `grastate.dat` inspection → bootstrap the most advanced node → join the others in sequence |
| **Analytics** | Same dataset in InnoDB and ColumnStore to compare row-store vs column-store aggregation |

> The cluster configuration files and ColumnStore scripts ran on the EC2 nodes and are not part of this repository snapshot. This page documents what was deployed and tested.

## Topology

The Silver database was migrated from a single MariaDB instance to a **three-node MariaDB Galera cluster**, with each node on its own AWS EC2 instance. Each node keeps its data directory on a dedicated **EBS volume**, so cluster state survives instance stops. Galera replicates InnoDB writes synchronously (virtually synchronous, certification-based), which means a commit on any node is visible on every node.

```
          ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
 writes → │   node 1     │◄───►│   node 2     │◄───►│   node 3     │
          │ InnoDB       │     │ InnoDB       │     │ InnoDB       │
          │ EBS volume   │     │ EBS volume   │     │ + ColumnStore│
          └──────────────┘     └──────────────┘     └──────────────┘
                       wsrep synchronous replication (port 4567)
```

Each node's configuration set the Galera provider, a shared cluster name, the `gcomm://` address list of all three nodes, a unique node name and address, and the replication settings Galera requires (such as row-based binary logging and interleaved auto-increment locking). Automatic restart was disabled on purpose (see below).

## Why bootstrap is manual

The AWS Learner Lab environment stops instances after a session limit, and the three nodes go down in an unpredictable order. If every node were allowed to auto-start, a node with stale data could form a new primary component and the cluster would diverge. Recovery therefore follows a manual protocol:

1. Inspect `grastate.dat` on every node's data volume and compare `seqno` (the last committed transaction).
2. If every node reports `seqno: -1` (unclean shutdown), recover the position with `mariadbd --wsrep-recover` on each node.
3. Bootstrap **only** the most advanced node, with `galera_new_cluster`. Set `safe_to_bootstrap: 1` only on that node, and only after confirming it holds the highest seqno.
4. Start the remaining nodes one at a time. Each joins through IST or SST.
5. Verify with `SHOW STATUS LIKE 'wsrep_cluster_size'` (expected 3) and `wsrep_local_state_comment` (expected `Synced`) on every node.

## Failover test

A controlled single-node failure was run against the replicated `dispatches` table (4,941 rows):

| Step | Result |
|---|---|
| All three nodes synchronized | `wsrep_cluster_size = 3` |
| MariaDB stopped on node 1 | Nodes 2 and 3 kept quorum (2 of 3) and stayed `Primary` |
| New dispatch inserted through node 2 | Committed |
| Row read from node 3 | Present, so writes replicated with one node down |
| Node 1 restarted | Rejoined, caught up and returned to `Synced`; cluster size back to 3 |

Two of three nodes is still a majority, so the cluster kept accepting writes. Losing a second node would drop the survivor to a non-primary state, which is the expected protection against split-brain.

## ColumnStore: row store vs column store

MariaDB ColumnStore was installed on node 3, and the same analytical dataset was created in both InnoDB and ColumnStore. Aggregation queries were compared across the two engines: dispatch counts, total labor cost, average service hours and warranty claim amounts. The point was to show the trade-off. InnoDB (row-oriented, indexed) suits the OLTP point lookups the RAG layer makes. ColumnStore (column-oriented, compressed, scans only the columns referenced) suits wide scans and aggregates.

