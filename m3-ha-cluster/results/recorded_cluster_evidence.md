# Recorded cluster evidence (AWS, October 2026)

Transcribed from the screenshots in the Milestone 3 report. The cluster ran on
three Ubuntu `t3.micro` EC2 instances in `us-east-1b`; the private addresses
below belonged to those (now terminated) instances.

## Nodes and storage

| Node | Private IP | Role |
|---|---|---|
| gigavolt-1 | 172.31.35.66 | initial bootstrap node |
| gigavolt-2 | 172.31.37.242 | surviving write node during the failover test |
| gigavolt-3 | 172.31.34.131 | Galera member + ColumnStore |

```
ubuntu@ip-172-31-34-131:~$ df -h /var/lib/mysql
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme1n1    9.8G  305M  9.0G   4% /var/lib/mysql
```

## Security group `milestone3-sg` (inbound)

| Protocol | Port | Source | Purpose |
|---|---|---|---|
| TCP | 22 | 0.0.0.0/0 | SSH administration |
| TCP | 3306 | milestone3-sg | MariaDB client connections |
| TCP | 4567 | milestone3-sg | Galera group communication |
| UDP | 4567 | milestone3-sg | Galera group communication over UDP (used only with multicast) |
| TCP | 4568 | milestone3-sg | Incremental state transfer (IST) |
| TCP | 4444 | milestone3-sg | Full state snapshot transfer (SST) |

## Cluster status (gigavolt-3)

```
wsrep_local_state_comment | Synced
wsrep_cluster_size        | 3
wsrep_cluster_status      | Primary
wsrep_ready               | ON
```

## Replication

`SELECT COUNT(*) AS dispatch_count FROM gigavolt.dispatches;` returned **4,941**
on gigavolt-1, gigavolt-2 and gigavolt-3.

## ColumnStore benchmark (gigavolt-3)

| Table | Engine | Rows |
|---|---|---:|
| gigavolt.dispatches | InnoDB | 4,941 |
| analytics_innodb | InnoDB | 494,100 |
| analytics_columnstore | ColumnStore | 494,100 |

Single profiled run of the same `GROUP BY model` aggregation
(`SHOW PROFILES`): InnoDB **0.62215066 s**, ColumnStore **0.22398362 s**
(about 64% lower elapsed time). Both engines returned identical aggregates;
see [`columnstore_benchmark.csv`](columnstore_benchmark.csv). One run, not an
averaged benchmark.

## Failover test (2026-10-11)

With MariaDB stopped on gigavolt-1, on gigavolt-2:

```
wsrep_cluster_size        | 2
wsrep_cluster_status      | Primary
wsrep_local_state_comment | Synced

INSERT INTO gigavolt.failover_test (test_id, message)
VALUES (3, 'Failover test while Node 1 is down');      -- Query OK, 1 row affected
```

On gigavolt-3:

```
| test_id | message                            | created_at          |
|       3 | Failover test while Node 1 is down | 2026-10-11 03:49:31 |
```

After `systemctl start mariadb` on gigavolt-1: `wsrep_cluster_size = 3`,
`Primary`, `Synced`, and the row above was present on gigavolt-1.
