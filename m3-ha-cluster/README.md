# Milestone 3 · High-Availability Galera Cluster & ColumnStore Analytics

The Silver database moves from one MariaDB instance to a **three-node Galera cluster** on AWS EC2. Each node keeps its data on its own EBS volume, auto-restart is disabled so recovery after the Learner Lab's forced shutdowns is a deliberate manual bootstrap, failover was tested under a live write, and **ColumnStore** on node 3 was benchmarked against InnoDB on the same analytical workload.

| | |
|---|---|
| **Cluster** | 3 × Ubuntu `t3.micro` · MariaDB + Galera 4 · ~10 GiB EBS volume per node at `/var/lib/mysql` |
| **State** | `wsrep_cluster_size = 3` · `Primary` · `Synced` · `wsrep_ready = ON`; 4,941 dispatches on every node |
| **Failover** | Node 1 stopped → 2-node Primary kept accepting writes → node 1 rejoined with a normal start |
| **Analytics** | 494,100-row aggregation: InnoDB **0.622 s** vs ColumnStore **0.224 s** (single profiled run, ~64% lower) |
| **Recovery tooling** | Per-node state report, cluster-wide bootstrap selection, runbook; rehearsed on a local 3-node cluster (25/25 checks) |

## What's here

| Path | Contents | Provenance |
|---|---|---|
| [`config/60-galera.gigavolt-{1,2,3}.cnf`](config/) | Node configuration, installed as `/etc/mysql/mariadb.conf.d/60-galera.cnf` | Recovered verbatim from the M3 report |
| [`config/mariadb-no-autorestart.conf`](config/mariadb-no-autorestart.conf) | systemd override `Restart=no` | Recovered setting |
| [`sql/cluster_status.sql`](sql/cluster_status.sql) · [`replication_check.sql`](sql/replication_check.sql) | Health and per-node replication checks | Rebuilt from the documented checks |
| [`sql/failover_test.sql`](sql/failover_test.sql) | Step-by-step single-node failover test | Rebuilt from the recorded run |
| [`sql/columnstore_analytics.sql`](sql/columnstore_analytics.sql) · [`scripts/load_columnstore.sh`](scripts/load_columnstore.sh) | InnoDB vs ColumnStore dataset, batch loader, profiled benchmark | Rebuilt; regenerates the recorded aggregates exactly |
| [`scripts/gigavolt-galera-recovery.sh`](scripts/gigavolt-galera-recovery.sh) | Per-node health + `grastate.dat` report | Rebuilt from the documented purpose |
| [`scripts/gigavolt_m3_demo.sh`](scripts/gigavolt_m3_demo.sh) | Read-only cluster walkthrough | Rebuilt from the documented purpose |
| [`scripts/select_bootstrap_node.sh`](scripts/select_bootstrap_node.sh) | Cluster-wide choice of the safe bootstrap node | **New**: completes the item listed as unfinished in October |
| [`GIGAVOLT_RECOVERY.md`](GIGAVOLT_RECOVERY.md) | Recovery runbook | Rebuilt and extended |
| [`local-test/`](local-test/) | 3-node Galera on one machine + full rehearsal | **New** |
| [`results/`](results/) | Recorded AWS evidence, benchmark CSV, local rehearsal log | Recorded / local |

## Run it

```bash
# On each node: health and saved state
sudo m3-ha-cluster/scripts/gigavolt-galera-recovery.sh

# After a full outage: which node may bootstrap?
m3-ha-cluster/scripts/select_bootstrap_node.sh --ssh gigavolt-1 gigavolt-2 gigavolt-3

# On gigavolt-3: build and benchmark the analytical tables
sudo mariadb < m3-ha-cluster/sql/columnstore_analytics.sql

# Anywhere (root, Ubuntu): rehearse everything on a local 3-node cluster
mariadb-dump --databases gigavolt --routines --triggers > gigavolt_dump.sql
sudo m3-ha-cluster/local-test/rehearse.sh gigavolt_dump.sql
```

## Architecture

```
                         milestone3-sg (3306, 4567 tcp/udp, 4568, 4444 between members)
      ┌────────────────────┐      ┌────────────────────┐      ┌────────────────────┐
      │ gigavolt-1         │◄────►│ gigavolt-2         │◄────►│ gigavolt-3         │
      │ 172.31.35.66       │      │ 172.31.37.242      │      │ 172.31.34.131      │
      │ InnoDB · Galera    │      │ InnoDB · Galera    │      │ InnoDB · Galera    │
      │ EBS /var/lib/mysql │      │ EBS /var/lib/mysql │      │ + ColumnStore      │
      └────────────────────┘      └────────────────────┘      └────────────────────┘
          initial bootstrap         write node in failover      analytics workload
```

* **Synchronous, certification-based replication.** A commit on any node is certified by the group before it returns, so every node holds the same InnoDB data and any node accepts writes.
* **Quorum.** Two of three nodes is a majority, so the cluster survives one failure. A lone node goes `non-Primary` and stops accepting writes rather than risk split-brain.
* **Persistent state.** `/var/lib/mysql` sits on a dedicated EBS volume (`/dev/nvme1n1`, 9.8 G), so data and `grastate.dat` survive instance stops.
* **Security group.** MariaDB and Galera ports are open only between members of `milestone3-sg`; only SSH is open externally ([details](results/recorded_cluster_evidence.md#security-group-milestone3-sg-inbound)).

The shared configuration ([full files](config/)):

```ini
[galera]
wsrep_cluster_name    = "Gigavolt_Galera_Cluster"
wsrep_provider        = "/usr/lib/galera/libgalera_smm.so"
wsrep_cluster_address = "gcomm://172.31.35.66,172.31.37.242,172.31.34.131"
wsrep_on              = ON
binlog_format         = ROW          # Galera replicates row images
innodb_autoinc_lock_mode = 2         # interleaved auto-increment, required by Galera
wsrep_node_name       = "gigavolt-N" # per node
wsrep_node_address    = "<node IP>"  # per node
bind-address          = 0.0.0.0
```

## Why bootstrap is manual

The Learner Lab stops all three instances, in an unpredictable order. If every node auto-started, a node with stale data could form a new primary component and the cluster's histories would diverge. So `mariadb.service` has `Restart=no`, and recovery follows the [runbook](GIGAVOLT_RECOVERY.md):

1. Read `grastate.dat` on every node (`gigavolt-galera-recovery.sh`).
2. Recover unknown positions (`seqno: -1`) with `mariadbd --wsrep-recover`.
3. Bootstrap **only** the most advanced node with `galera_new_cluster` (`select_bootstrap_node.sh` decides).
4. Start the other nodes one at a time with `systemctl start mariadb`.

During the milestone, steps 1–2 were scripted per node and the cross-node choice in step 3 was a manual comparison. `select_bootstrap_node.sh` now automates it.

## Failover test (recorded on AWS, 2026-10-11)

| Step | Node | Result |
|---|---|---|
| Baseline | any | `failover_test` table created, cluster 3 / Primary / Synced |
| Stop MariaDB | gigavolt-1 | Nodes 2 and 3 stay up |
| Check | gigavolt-2 | `wsrep_cluster_size = 2`, `Primary`, `Synced` |
| Write | gigavolt-2 | `(3, 'Failover test while Node 1 is down')` committed at 03:49:31 |
| Read | gigavolt-3 | Row 3 present, so replication continued with one node down |
| Rejoin | gigavolt-1 | `systemctl start mariadb` (not a new bootstrap) |
| Verify | gigavolt-1 | 3 / Primary / Synced, row 3 present |

Transcripts: [`results/recorded_cluster_evidence.md`](results/recorded_cluster_evidence.md).

## ColumnStore: row store vs column store

Both tables hold the same **494,100 rows**: every Silver dispatch joined to its equipment model and total warranty-claim amount, replicated 100×. The operational `dispatches` table (4,941 rows) is untouched.

```sql
SELECT model, COUNT(*) AS dispatches,
       ROUND(SUM(labor_cost), 2) AS total_labor_cost,
       ROUND(AVG(hours_spent), 2) AS avg_hours,
       ROUND(SUM(total_claim_amount), 2) AS total_claim_amount
FROM gigavolt.analytics_columnstore      -- and analytics_innodb
GROUP BY model ORDER BY model;
```

| model | dispatches | total_labor_cost | avg_hours | total_claim_amount |
|---|---:|---:|---:|---:|
| X-12000 | 110,100 | 116,648,600.00 | 9.49 | 49,312,092.00 |
| X-3000 | 90,300 | 88,013,450.00 | 8.43 | 42,103,631.00 |
| X-5000 | 94,600 | 110,255,150.00 | 10.83 | 43,104,677.00 |
| X-7000 | 95,400 | 103,113,850.00 | 9.56 | 44,574,893.00 |
| X-9000 | 103,700 | 119,080,600.00 | 9.95 | 45,800,352.00 |

| Engine | Elapsed (`SHOW PROFILES`) |
|---|---:|
| InnoDB | 0.6222 s |
| ColumnStore | **0.2240 s** |

Both engines returned identical aggregates. ColumnStore reads only the four columns the query touches, stored compressed and column by column. InnoDB reads whole rows through the clustered index. The timings come from one profiled run on a `t3.micro`, not an averaged benchmark.

Two details make this work on a Galera node:

* **`SET SESSION wsrep_on = OFF`.** Galera replicates only InnoDB, and only node 3 has the ColumnStore engine, so the analytical DDL must not replicate. In the local rehearsal the tables existed only on node 3.
* **Reproducible dataset.** Re-running [`columnstore_analytics.sql`](sql/columnstore_analytics.sql) against the Silver data regenerates all 20 recorded aggregate values exactly.

## Local rehearsal

[`local-test/rehearse.sh`](local-test/rehearse.sh) runs three MariaDB 10.11 + Galera 4 nodes on one machine, with the same settings as the EC2 config, and checks every procedure. The [log](results/local_rehearsal.log) shows 25/25 checks passing:

| Scenario | What it proves |
|---|---|
| Bootstrap + join | 3 / Primary / Synced on every node |
| Load through node 1 | 4,941 dispatches and all 4 M2 triggers on every node |
| Single-node failover | The recorded AWS behavior reproduced: 2-node Primary, write on 2 read on 3, IST rejoin |
| Full outage, clean stops | `select_bootstrap_node.sh` picks the last node down; cluster recovers |
| Stale node + two crashes | Selection **refuses** until positions are recovered, then picks node 2 (seqno 135) over the stale node 1 (133); writes made after node 1 left survive on all nodes |

The harness seeds nodes 2 and 3 from a snapshot of node 1, because the container used for testing cannot run a full state transfer (SST). Joins and rejoins still go through Galera's incremental state transfer.

## Limitations

* The AWS failover test covered a **single-node outage**. Full three-node outage recovery was exercised only in the local rehearsal, not on the original EC2 cluster.
* The ColumnStore comparison is **one profiled run** per engine. The scripts make it repeatable, but no averaged benchmark was recorded.
* The original EC2 instances are terminated. The private IPs in the config files are historical.
