#!/usr/bin/env bash
# =============================================================================
# select_bootstrap_node.sh: decide which node may bootstrap after a FULL outage
# -----------------------------------------------------------------------------
# Added after Milestone 3. The original recovery script inspected one node at a
# time; choosing the bootstrap node across the cluster was still a manual step.
# This script automates that decision. It never starts or stops anything.
#
# Usage (from an admin host that can SSH to the nodes):
#   scripts/select_bootstrap_node.sh --ssh gigavolt-1 gigavolt-2 gigavolt-3
#
# Or with grastate.dat files already collected (name=path pairs):
#   scripts/select_bootstrap_node.sh gigavolt-1=./g1.dat gigavolt-2=./g2.dat gigavolt-3=./g3.dat
#
# Add positions from `mariadbd --wsrep-recover` for nodes that report seqno -1:
#   ... --recovered gigavolt-2=1047
#
# Decision rules, in order:
#   1. All nodes must share one cluster UUID, otherwise stop (split history).
#   2. A node with safe_to_bootstrap: 1 shut down last: choose it.
#   3. Any node still at seqno -1 without a recovered position: stop and ask
#      for --wsrep-recover, because its true position is unknown.
#   4. Otherwise choose the highest seqno. A tie means the nodes are identical;
#      the first listed is chosen.
#
# Exit codes: 0 = recommendation printed, 2 = unsafe to decide, 1 = usage error.
# Environment: DATADIR (default /var/lib/mysql), SSH (default "ssh").
# =============================================================================
set -euo pipefail

DATADIR=${DATADIR:-/var/lib/mysql}
SSH=${SSH:-ssh}

declare -a NODES=()
declare -A UUID=() SEQNO=() SAFE=() RECOVERED=()

usage() { sed -n '2,32p' "$0"; exit 1; }

field() {  # field <name> <grastate text>
    printf '%s\n' "$2" | awk -F': *' -v k="$1" '$1 == k {print $2; exit}'
}

add_node() {  # add_node <name> <grastate text>
    local name=$1 text=$2
    NODES+=("$name")
    UUID[$name]=$(field uuid "$text")
    SEQNO[$name]=$(field seqno "$text")
    SAFE[$name]=$(field safe_to_bootstrap "$text")
    [[ -n "${UUID[$name]}" && -n "${SEQNO[$name]}" ]] \
        || { echo "Could not parse grastate.dat for $name" >&2; exit 1; }
}

mode=files
[[ $# -gt 0 ]] || usage
while [[ $# -gt 0 ]]; do
    case "$1" in
        --ssh)       mode=ssh; shift ;;
        --recovered) RECOVERED[${2%%=*}]=${2#*=}; shift 2 ;;
        -h|--help)   usage ;;
        *=*)         add_node "${1%%=*}" "$(cat "${1#*=}")"; shift ;;
        *)           [[ $mode == ssh ]] || usage
                     add_node "$1" "$($SSH "$1" sudo cat "$DATADIR/grastate.dat")"; shift ;;
    esac
done

(( ${#NODES[@]} >= 2 )) || { echo "Give at least two nodes" >&2; exit 1; }

printf '%-14s %-38s %8s %10s %s\n' NODE UUID SEQNO RECOVERED SAFE_TO_BOOTSTRAP
for n in "${NODES[@]}"; do
    printf '%-14s %-38s %8s %10s %s\n' "$n" "${UUID[$n]}" "${SEQNO[$n]}" \
        "${RECOVERED[$n]:--}" "${SAFE[$n]:-?}"
done
echo

# Rule 1: one shared history.
first_uuid=${UUID[${NODES[0]}]}
for n in "${NODES[@]}"; do
    if [[ "${UUID[$n]}" != "$first_uuid" ]]; then
        echo "UNSAFE: nodes report different cluster UUIDs; histories have diverged."
        echo "Do not bootstrap. Investigate which node holds the authoritative data."
        exit 2
    fi
done

# Rule 2: the node that shut down last.
for n in "${NODES[@]}"; do
    if [[ "${SAFE[$n]}" == 1 ]]; then
        echo "BOOTSTRAP: $n (safe_to_bootstrap: 1, it shut down last)"
        echo "  on $n:      sudo galera_new_cluster"
        echo "  then others, one at a time: sudo systemctl start mariadb"
        exit 0
    fi
done

# Rules 3 and 4: highest known position.
best=''
best_seq=-2
for n in "${NODES[@]}"; do
    seq=${RECOVERED[$n]:-${SEQNO[$n]}}
    if [[ "$seq" == -1 ]]; then
        echo "UNSAFE: $n has seqno -1 (unclean shutdown) and no recovered position."
        echo "  on $n: sudo -u mysql mariadbd --wsrep-recover"
        echo "  then re-run with --recovered $n=<seqno from 'Recovered position'>"
        exit 2
    fi
    if (( seq > best_seq )); then best=$n best_seq=$seq; fi
done

echo "BOOTSTRAP: $best (highest committed seqno: $best_seq)"
echo "  on $best: set safe_to_bootstrap: 1 in $DATADIR/grastate.dat, then: sudo galera_new_cluster"
echo "  then others, one at a time: sudo systemctl start mariadb"
