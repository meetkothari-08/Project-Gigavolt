#!/usr/bin/env bash
# =============================================================================
# gigavolt_m3_demo.sh: read-only walkthrough of the cluster for a demo
# -----------------------------------------------------------------------------
# For each node: identity, wsrep status and the replicated dispatch count; then
# the storage engines on the ColumnStore node. Issues SELECT and SHOW only.
#
#   NODES="172.31.35.66 172.31.37.242 172.31.34.131" \
#   MARIADB_ARGS="-u gigavolt_admin -p" scripts/gigavolt_m3_demo.sh
#
# Environment: NODES (hosts, default gigavolt-1 gigavolt-2 gigavolt-3),
#              COLUMNSTORE_NODE (default: last node), MARIADB_ARGS (extra client
#              options), PORTS (optional ports matching NODES, for local tests).
# =============================================================================
set -euo pipefail

read -r -a nodes <<< "${NODES:-gigavolt-1 gigavolt-2 gigavolt-3}"
read -r -a ports <<< "${PORTS:-}"
read -r -a extra <<< "${MARIADB_ARGS:-}"
columnstore_node=${COLUMNSTORE_NODE:-${nodes[-1]}}

q() {  # q <node-index> <sql>
    local args=(-h "${nodes[$1]}")
    [[ -n "${ports[$1]:-}" ]] && args+=(-P "${ports[$1]}" --protocol=TCP)
    mariadb "${args[@]}" "${extra[@]}" --table -e "$2"
}

for i in "${!nodes[@]}"; do
    printf '\n========== %s ==========\n' "${nodes[$i]}"
    q "$i" "SELECT @@wsrep_node_name AS node, @@wsrep_node_address AS address;
            SHOW STATUS WHERE Variable_name IN ('wsrep_cluster_size','wsrep_cluster_status',
                                                'wsrep_local_state_comment','wsrep_ready');
            SELECT COUNT(*) AS dispatch_count FROM gigavolt.dispatches;"
done

for i in "${!nodes[@]}"; do
    if [[ "${nodes[$i]}" == "$columnstore_node" ]]; then
        printf '\n========== engines on %s ==========\n' "$columnstore_node"
        q "$i" "SELECT ENGINE, SUPPORT FROM information_schema.ENGINES
                 WHERE ENGINE IN ('Columnstore', 'InnoDB', 'SEQUENCE');"
    fi
done
