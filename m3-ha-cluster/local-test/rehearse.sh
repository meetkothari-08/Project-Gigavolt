#!/usr/bin/env bash
# =============================================================================
# rehearse.sh: replay every Milestone 3 procedure on a local 3-node cluster
# -----------------------------------------------------------------------------
#   1. bootstrap gigavolt-1, join gigavolt-2 and gigavolt-3
#   2. load the Silver database through gigavolt-1, check replication everywhere
#   3. single-node failover: stop node 1, write on node 2, read on node 3, rejoin
#   4. full outage, clean stops (1 -> 2 -> 3): select + bootstrap the last node
#   5. full outage with a stale node and two crashed nodes: refuse, recover
#      positions, bootstrap the most advanced node, prove no write was lost
#
#   sudo m3-ha-cluster/local-test/rehearse.sh /path/to/gigavolt_dump.sql
#
# The dump is a full logical dump of a deployed gigavolt database:
#   mariadb-dump --databases gigavolt --routines --triggers > gigavolt_dump.sql
# Exits non-zero at the first failed expectation.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
M3="$(dirname "$HERE")"
GV="$HERE/galera_local.sh"
DUMP=${1:?usage: rehearse.sh <gigavolt_dump.sql>}
GV_BASE=${GV_BASE:-/var/lib/gv-galera}
export GV_BASE

q()      { mariadb --socket="/run/mysqld/gv$1.sock" -uroot -N -e "$2"; }
status() { q "$1" "SHOW STATUS WHERE Variable_name IN ('wsrep_cluster_size','wsrep_cluster_status',
               'wsrep_local_state_comment')" | sort | awk '{printf "%s ", $2}'; }
expect() {  # expect <description> <actual> <expected>
    if [[ "$2" == "$3" ]]; then printf '  PASS  %s (%s)\n' "$1" "$2"
    else printf '  FAIL  %s: got "%s", expected "%s"\n' "$1" "$2" "$3"; exit 1; fi
}
grastates() {
    for n in 1 2 3; do printf 'gigavolt-%s=%s/node%s/data/grastate.dat ' "$n" "$GV_BASE" "$n"; done
}

echo "== 1. Bootstrap"
"$GV" up >/dev/null
for n in 1 2 3; do expect "gigavolt-$n state" "$(status "$n")" "3 Primary Synced "; done

echo "== 2. Load Silver through gigavolt-1, read everywhere"
mariadb --socket=/run/mysqld/gv1.sock -uroot < "$DUMP"
sleep 2
for n in 1 2 3; do
    expect "gigavolt-$n dispatches" "$(q "$n" 'SELECT COUNT(*) FROM gigavolt.dispatches')" 4941
    expect "gigavolt-$n M2 triggers" \
        "$(q "$n" "SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='gigavolt'")" 4
done

echo "== 3. Single-node failover"
q 1 "CREATE TABLE gigavolt.failover_test (test_id INT PRIMARY KEY, message VARCHAR(255) NOT NULL,
     created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB;
     INSERT INTO gigavolt.failover_test (test_id, message) VALUES (1, 'Baseline: all three nodes online');"
"$GV" stop 1
expect "gigavolt-2 with node 1 down" "$(status 2)" "2 Primary Synced "
q 2 "INSERT INTO gigavolt.failover_test (test_id, message) VALUES (3, 'Failover test while Node 1 is down')"
expect "write on node 2 read on node 3" \
    "$(q 3 'SELECT message FROM gigavolt.failover_test WHERE test_id = 3')" "Failover test while Node 1 is down"
"$GV" start 1
sleep 2
expect "gigavolt-1 after rejoin" "$(status 1)" "3 Primary Synced "
expect "gigavolt-1 caught up" "$(q 1 'SELECT COUNT(*) FROM gigavolt.failover_test')" 2

echo "== 4. Full outage, clean stops 1 -> 2 -> 3"
for n in 1 2 3; do "$GV" stop "$n"; done
# shellcheck disable=SC2046
decision=$("$M3/scripts/select_bootstrap_node.sh" $(grastates) | grep '^BOOTSTRAP')
echo "  $decision"
expect "chosen node" "$(awk '{print $2}' <<< "$decision")" gigavolt-3
"$GV" bootstrap 3; "$GV" start 1; "$GV" start 2
sleep 2
for n in 1 2 3; do expect "gigavolt-$n state" "$(status "$n")" "3 Primary Synced "; done

echo "== 5. Stale node + two crashed nodes"
"$GV" stop 1
q 2 "INSERT INTO gigavolt.failover_test (test_id, message) VALUES (4, 'Written after node 1 left'), (5, 'Second late write')"
"$GV" kill 2; "$GV" kill 3
set +e
# shellcheck disable=SC2046
"$M3/scripts/select_bootstrap_node.sh" $(grastates) > /dev/null
rc=$?
set -e
expect "decision without recovered positions is refused (exit code)" "$rc" 2
r2=$("$GV" recover 2); r3=$("$GV" recover 3)
echo "  recovered: gigavolt-2 $r2, gigavolt-3 $r3"
# shellcheck disable=SC2046
decision=$("$M3/scripts/select_bootstrap_node.sh" $(grastates) \
    --recovered "gigavolt-2=${r2##*:}" --recovered "gigavolt-3=${r3##*:}" | grep '^BOOTSTRAP')
echo "  $decision"
expect "chosen node is not the stale gigavolt-1" "$(awk '{print $2}' <<< "$decision")" gigavolt-2
sed -i 's/^safe_to_bootstrap: 0/safe_to_bootstrap: 1/' "$GV_BASE/node2/data/grastate.dat"
"$GV" bootstrap 2; "$GV" start 3; "$GV" start 1
sleep 2
for n in 1 2 3; do
    expect "gigavolt-$n state" "$(status "$n")" "3 Primary Synced "
    expect "gigavolt-$n kept late writes" \
        "$(q "$n" 'SELECT GROUP_CONCAT(test_id ORDER BY test_id) FROM gigavolt.failover_test')" "1,3,4,5"
done

echo
echo "All Milestone 3 procedures rehearsed successfully."
