#!/usr/bin/env bash
# =============================================================================
# gigavolt-galera-recovery.sh: health and saved-state report for ONE node
# -----------------------------------------------------------------------------
# Run on each Galera node, before and after a restart:
#   sudo scripts/gigavolt-galera-recovery.sh
#
# Reports:
#   1. whether the MariaDB service is running
#   2. live wsrep status when it is (cluster size, status, local state, ready)
#   3. the saved Galera state in grastate.dat: cluster UUID, last committed
#      seqno, and safe_to_bootstrap, which is what decides the bootstrap node
#
# It changes nothing. To choose the bootstrap node across all three nodes, see
# select_bootstrap_node.sh and GIGAVOLT_RECOVERY.md.
#
# Environment: DATADIR (default /var/lib/mysql), SERVICE (default mariadb),
#              MARIADB_CMD (default "mariadb"), SKIP_SYSTEMCTL=1 for non-systemd hosts.
# =============================================================================
set -uo pipefail

DATADIR=${DATADIR:-/var/lib/mysql}
SERVICE=${SERVICE:-mariadb}
MARIADB_CMD=${MARIADB_CMD:-mariadb}
GRASTATE="$DATADIR/grastate.dat"

section() { printf '\n== %s\n' "$1"; }

section "Node"
echo "host: $(hostname)   data directory: $DATADIR"

section "Service"
running=false
if [[ "${SKIP_SYSTEMCTL:-0}" != 1 ]] && command -v systemctl >/dev/null; then
    state=$(systemctl is-active "$SERVICE" 2>/dev/null || true)
    echo "$SERVICE: ${state:-unknown}"
    [[ "$state" == active ]] && running=true
fi
if ! $running && $MARIADB_CMD -e 'SELECT 1' >/dev/null 2>&1; then
    running=true
    echo "server answers queries"
fi
$running || echo "server is not running"

if $running; then
    section "Live cluster status"
    $MARIADB_CMD --table -e "
        SHOW STATUS WHERE Variable_name IN (
            'wsrep_cluster_size', 'wsrep_cluster_status',
            'wsrep_local_state_comment', 'wsrep_ready',
            'wsrep_last_committed', 'wsrep_cluster_state_uuid');"

    size=$($MARIADB_CMD -N -e "SHOW STATUS LIKE 'wsrep_cluster_size'" | awk '{print $2}')
    status=$($MARIADB_CMD -N -e "SHOW STATUS LIKE 'wsrep_cluster_status'" | awk '{print $2}')
    local_state=$($MARIADB_CMD -N -e "SHOW STATUS LIKE 'wsrep_local_state_comment'" | awk '{print $2}')
    if [[ "$size" == 3 && "$status" == Primary && "$local_state" == Synced ]]; then
        echo "HEALTHY: 3-node Primary component, this node Synced"
    else
        echo "DEGRADED: size=$size status=$status local_state=$local_state"
    fi
fi

section "Saved state ($GRASTATE)"
if [[ ! -r "$GRASTATE" ]]; then
    echo "grastate.dat not readable (run with sudo?) or node never joined a cluster"
    exit 0
fi
grep -E '^(uuid|seqno|safe_to_bootstrap):' "$GRASTATE"

seqno=$(awk -F': *' '/^seqno:/ {print $2}' "$GRASTATE")
safe=$(awk -F': *' '/^safe_to_bootstrap:/ {print $2}' "$GRASTATE")

section "Interpretation"
if $running; then
    echo "Node is running: grastate.dat shows seqno -1 while the server is up; that is normal."
elif [[ "$safe" == 1 ]]; then
    echo "safe_to_bootstrap: 1, so this node shut down LAST and is the bootstrap candidate."
elif [[ "$seqno" == -1 ]]; then
    echo "seqno -1 after shutdown: unclean stop. Recover the position with:"
    echo "  sudo -u mysql mariadbd --wsrep-recover   (then read 'Recovered position' from the log)"
else
    echo "Clean stop at seqno $seqno, not marked safe_to_bootstrap."
    echo "Compare seqno on all nodes; bootstrap only the highest (select_bootstrap_node.sh)."
fi
