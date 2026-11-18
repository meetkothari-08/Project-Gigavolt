#!/usr/bin/env bash
# =============================================================================
# Deploy the Gigavolt MariaDB schema and programmability objects in order.
#
#   sql/deploy.sh                       # schema + objects, no data
#   sql/deploy.sh --seed silver.sql     # also load a data-only Silver seed
#   sql/deploy.sh --validate            # run the validation suites afterwards
#
# Connection settings come from the standard MariaDB client environment / option
# files (e.g. ~/.my.cnf) or from MARIADB_HOST, MARIADB_PORT, MARIADB_USER and
# MARIADB_PASSWORD. The seed file must contain INSERT statements only
# (mariadb-dump --no-create-info gigavolt customers equipment_models equipment
#  parts dispatches warranty_claims).
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATABASE="${MARIADB_DATABASE:-gigavolt}"
SEED_FILE=""
VALIDATE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --seed)     SEED_FILE="$2"; shift 2 ;;
        --validate) VALIDATE=true; shift ;;
        -h|--help)  sed -n '2,16p' "$0"; exit 0 ;;
        *)          echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

client_args=()
[[ -n "${MARIADB_HOST:-}"     ]] && client_args+=(--host="$MARIADB_HOST")
[[ -n "${MARIADB_PORT:-}"     ]] && client_args+=(--port="$MARIADB_PORT")
[[ -n "${MARIADB_USER:-}"     ]] && client_args+=(--user="$MARIADB_USER")
[[ -n "${MARIADB_PASSWORD:-}" ]] && export MYSQL_PWD="$MARIADB_PASSWORD"

log() { printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

run_sql() {
    local file="$1"
    log "Applying $(basename "$file")"
    mariadb "${client_args[@]}" --batch < "$file"
}

command -v mariadb >/dev/null || { echo "mariadb client not found" >&2; exit 1; }
mariadb "${client_args[@]}" -e 'SELECT 1' >/dev/null \
    || { echo "Cannot connect to MariaDB" >&2; exit 1; }

# Order matters: schema -> seed data -> objects that depend on data/tables.
run_sql "$SCRIPT_DIR/00_create_database.sql"
run_sql "$SCRIPT_DIR/01_bronze_schema.sql"
run_sql "$SCRIPT_DIR/02_silver_schema.sql"
run_sql "$SCRIPT_DIR/03_staging_and_quarantine.sql"
run_sql "$SCRIPT_DIR/11_audit_log.sql"

if [[ -n "$SEED_FILE" ]]; then
    [[ -f "$SEED_FILE" ]] || { echo "Seed file not found: $SEED_FILE" >&2; exit 1; }
    log "Loading Silver seed $(basename "$SEED_FILE")"
    # Load before the change-capture triggers so the bulk load is not audited.
    mariadb "${client_args[@]}" "$DATABASE" < "$SEED_FILE"
fi

run_sql "$SCRIPT_DIR/10_generated_columns.sql"
run_sql "$SCRIPT_DIR/12_audit_triggers.sql"
run_sql "$SCRIPT_DIR/13_rag_payload_procedure.sql"
run_sql "$SCRIPT_DIR/14_security_views.sql"

log "Deployment complete"

if $VALIDATE; then
    failures=0
    for check in 90_validate_integrity.sql 91_validate_programmability.sql; do
        log "Running $check"
        output="$(mariadb "${client_args[@]}" --batch --skip-column-names \
                  "$DATABASE" < "$SCRIPT_DIR/$check")"
        printf '%s\n' "$output" | awk -F'\t' '{printf "    %-55s %s\n", $1, $NF}'
        failures=$((failures + $(printf '%s\n' "$output" | grep -c 'FAIL$' || true)))
    done
    if (( failures > 0 )); then
        log "Validation finished with $failures failing check(s)"
        exit 1
    fi
    log "All validation checks passed"
fi
