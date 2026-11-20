#!/usr/bin/env bash
# =============================================================================
# galera_local.sh: run a 3-node Galera cluster on ONE Linux machine
# -----------------------------------------------------------------------------
# Rehearses the Milestone 3 procedures (bootstrap, failover, full-outage
# recovery) without three EC2 instances. Each node gets its own data directory,
# socket, SQL port and Galera ports; everything else matches config/60-galera.*.cnf.
#
# Requires: mariadb-server, galera-4, mariadb-backup (Ubuntu/Debian packages).
# Run as root.
#
#   galera_local.sh up                # init, bootstrap gigavolt-1, seed + join 2 and 3
#   galera_local.sh status            # wsrep status of every node
#   galera_local.sh stop N            # clean shutdown   (systemctl stop mariadb)
#   galera_local.sh kill N            # crash            (instance loses power)
#   galera_local.sh start N           # join the running cluster
#   galera_local.sh bootstrap N       # galera_new_cluster on node N
#   galera_local.sh recover N         # mariadbd --wsrep-recover, print position
#   galera_local.sh grastate N        # print node N's grastate.dat
#   galera_local.sh sql N "<sql>"     # run SQL on node N
#   galera_local.sh down              # stop all nodes and delete their data
#
# Node N listens on SQL port 331N, Galera port N4567 (IST N4568, SST N4569),
# socket /run/mysqld/gvN.sock; data lives under $GV_BASE (default /var/lib/gv-galera).
# Nodes 2 and 3 are seeded from a copy of node 1's data directory, so joining
# needs only an incremental state transfer (IST). That avoids a full SST,
# which some container kernels cannot run.
# =============================================================================
set -euo pipefail

GV_BASE=${GV_BASE:-/var/lib/gv-galera}

port()  { echo $((3310 + $1)); }
gport() { echo $((10000 * $1 + 4567)); }
dir()   { echo "$GV_BASE/node$1"; }
sock()  { echo "/run/mysqld/gv$1.sock"; }

write_cnf() {
    local n=$1 d
    d=$(dir "$n")
    cat > "$d/my.cnf" <<EOF
[mysqld]
datadir = $d/data
socket = $(sock "$n")
pid-file = $d/mysqld.pid
log-error = $d/error.log
port = $(port "$n")
bind-address = 127.0.0.1
user = root
innodb_buffer_pool_size = 64M

[galera]
wsrep_cluster_name = "Gigavolt_Galera_Cluster"
wsrep_provider = "/usr/lib/galera/libgalera_smm.so"
wsrep_cluster_address = "gcomm://127.0.0.1:$(gport 1),127.0.0.1:$(gport 2),127.0.0.1:$(gport 3)"
wsrep_on = ON
binlog_format = ROW
innodb_autoinc_lock_mode = 2
wsrep_node_name = "gigavolt-$n"
wsrep_node_address = "127.0.0.1:$(gport "$n")"
wsrep_provider_options = "base_port=$(gport "$n");ist.recv_addr=127.0.0.1:$(( $(gport "$n") + 1 ))"
wsrep_sst_receive_address = "127.0.0.1:$(( $(gport "$n") + 2 ))"
wsrep_sst_method = mariabackup
wsrep_sst_auth = root:
EOF
}

client() { mariadb --socket="$(sock "$1")" -uroot "${@:2}"; }

wait_up() {
    for _ in $(seq 1 90); do
        client "$1" -e "SELECT 1" >/dev/null 2>&1 && return 0
        sleep 1
    done
    echo "gigavolt-$1 did not come up; last log lines:" >&2
    tail -20 "$(dir "$1")/error.log" >&2
    return 1
}

launch() {  # launch <node> [extra mariadbd args]
    (mariadbd --defaults-file="$(dir "$1")/my.cnf" "${@:2}" >/dev/null 2>&1 &)
    wait_up "$1"
}

stop_node() {
    client "$1" -e "SHUTDOWN" 2>/dev/null || mariadb-admin --socket="$(sock "$1")" -uroot shutdown
    while [[ -f "$(dir "$1")/mysqld.pid" ]]; do sleep 0.5; done
}

case "${1:-}" in
    up)
        mkdir -p /run/mysqld
        for n in 1 2 3; do
            mkdir -p "$(dir "$n")/data"
            write_cnf "$n"
            mariadb-install-db --defaults-file="$(dir "$n")/my.cnf" --user=root \
                --auth-root-authentication-method=socket >/dev/null
        done
        launch 1 --wsrep-new-cluster
        stop_node 1
        for n in 2 3; do   # seed from node 1's snapshot
            find "$(dir "$n")/data" -mindepth 1 -delete
            cp -a "$(dir 1)/data/." "$(dir "$n")/data/"
            sed -i 's/^safe_to_bootstrap: 1/safe_to_bootstrap: 0/' "$(dir "$n")/data/grastate.dat"
        done
        launch 1 --wsrep-new-cluster
        launch 2
        launch 3
        "$0" status ;;
    status)
        for n in 1 2 3; do
            printf 'gigavolt-%s: ' "$n"
            client "$n" -N -e "SHOW STATUS WHERE Variable_name IN ('wsrep_cluster_size',
                'wsrep_cluster_status','wsrep_local_state_comment','wsrep_ready')" 2>/dev/null \
                | awk '{printf "%s=%s ", $1, $2} END {print ""}' || echo "down"
        done ;;
    stop)      stop_node "$2" ;;
    kill)      kill -9 "$(cat "$(dir "$2")/mysqld.pid")"; sleep 1; rm -f "$(dir "$2")/mysqld.pid" ;;
    start)     launch "$2" ;;
    bootstrap) launch "$2" --wsrep-new-cluster ;;
    recover)
        mariadbd --defaults-file="$(dir "$2")/my.cnf" --wsrep-recover >/dev/null 2>&1 || true
        grep "Recovered position" "$(dir "$2")/error.log" | tail -1 | sed 's/.*Recovered position: //' ;;
    grastate)  cat "$(dir "$2")/data/grastate.dat" ;;
    sql)       client "$2" --table -e "$3" ;;
    down)
        pids=()
        for n in 1 2 3; do
            [[ -f "$(dir "$n")/mysqld.pid" ]] && pids+=("$(cat "$(dir "$n")/mysqld.pid")")
        done
        for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
        for pid in "${pids[@]}"; do   # wait for a clean shutdown before deleting data
            for _ in $(seq 1 60); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
        done
        case "$GV_BASE" in
            */gv-galera*) find "$GV_BASE" -mindepth 1 -delete; rmdir "$GV_BASE" ;;
            *) echo "Refusing to delete $GV_BASE (path must contain 'gv-galera')" >&2; exit 1 ;;
        esac ;;
    *) sed -n '2,30p' "$0"; exit 1 ;;
esac
