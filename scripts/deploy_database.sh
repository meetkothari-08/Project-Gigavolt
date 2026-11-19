#!/usr/bin/env bash
# =============================================================================
# Deploy the Gigavolt MariaDB database: M1 lakehouse + M2 SQL automation.
#
#   scripts/deploy_database.sh                          # schema + objects, no data
#   scripts/deploy_database.sh --raw-dir data/raw/erp   # build Bronze -> Silver from the raw CSVs
#   scripts/deploy_database.sh --seed silver.sql        # or load a data-only Silver seed
#   scripts/deploy_database.sh --validate               # run the validation suites afterwards
#
# Connection settings come from the standard MariaDB client option files
# (e.g. ~/.my.cnf) or from MARIADB_HOST, MARIADB_PORT, MARIADB_USER and
# MARIADB_PASSWORD. A seed must contain INSERT statements only
# (mariadb-dump --no-create-info --complete-insert gigavolt customers
#  equipment_models equipment parts dispatches warranty_claims).
# =============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
M1="$REPO_DIR/m1-erp-pipeline"
M2="$REPO_DIR/m2-database-logic"
DATABASE="${MARIADB_DATABASE:-gigavolt}"
SEED_FILE=""
RAW_DIR=""
VALIDATE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --seed)     SEED_FILE="$2"; shift 2 ;;
        --raw-dir)  RAW_DIR="$2"; shift 2 ;;
        --validate) VALIDATE=true; shift ;;
        -h|--help)  sed -n '2,15p' "$0"; exit 0 ;;
        *)          echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [[ -n "$SEED_FILE" && -n "$RAW_DIR" ]]; then
    echo "Use either --seed or --raw-dir, not both" >&2; exit 2
fi

client_args=()
[[ -n "${MARIADB_HOST:-}"     ]] && client_args+=(--host="$MARIADB_HOST")
[[ -n "${MARIADB_PORT:-}"     ]] && client_args+=(--port="$MARIADB_PORT")
[[ -n "${MARIADB_USER:-}"     ]] && client_args+=(--user="$MARIADB_USER")
[[ -n "${MARIADB_PASSWORD:-}" ]] && export MYSQL_PWD="$MARIADB_PASSWORD"

log() { printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

run_sql() {
    log "Applying ${1#"$REPO_DIR"/}"
    mariadb "${client_args[@]}" --batch < "$1"
}

command -v mariadb >/dev/null || { echo "mariadb client not found" >&2; exit 1; }
mariadb "${client_args[@]}" -e 'SELECT 1' >/dev/null \
    || { echo "Cannot connect to MariaDB" >&2; exit 1; }

# --- M1: schema and cleansing functions ---------------------------------------
run_sql "$M1/sql/00_create_database.sql"
run_sql "$M1/sql/01_bronze_schema.sql"
run_sql "$M1/sql/02_silver_schema.sql"
run_sql "$M1/sql/03_staging_and_quarantine.sql"
run_sql "$M1/sql/04_cleansing_functions.sql"
run_sql "$M2/sql/02_audit_log.sql"

# --- Data: loaded before the change-capture triggers so it is not audited ----
if [[ -n "$RAW_DIR" ]]; then
    [[ -f "$RAW_DIR/customers.csv" ]] || { echo "No ERP CSVs in: $RAW_DIR" >&2; exit 1; }
    mariadb "${client_args[@]}" "$DATABASE" -e \
        "DROP TRIGGER IF EXISTS trg_Dispatches_After_Insert;
         DROP TRIGGER IF EXISTS trg_Dispatches_Before_Update;"
    log "Loading Bronze from $RAW_DIR"
    # LOAD DATA LOCAL resolves the CSV names relative to the working directory.
    (cd "$RAW_DIR" && mariadb "${client_args[@]}" --local-infile=1 --batch \
        < "$M1/sql/05_load_bronze.sql")
    run_sql "$M1/sql/06_cleanse_to_silver.sql"
fi

if [[ -n "$SEED_FILE" ]]; then
    [[ -f "$SEED_FILE" ]] || { echo "Seed file not found: $SEED_FILE" >&2; exit 1; }
    log "Loading Silver seed $(basename "$SEED_FILE")"
    mariadb "${client_args[@]}" "$DATABASE" < "$SEED_FILE"
fi

# --- M2: SQL automation -----------------------------------------------------------
run_sql "$M2/sql/01_generated_columns.sql"
run_sql "$M2/sql/03_audit_triggers.sql"
run_sql "$M2/sql/04_rag_payload_procedure.sql"
run_sql "$M2/sql/05_security_views.sql"

log "Deployment complete"

if $VALIDATE; then
    failures=0
    for check in "$M1/validation/validate_integrity.sql" \
                 "$M2/validation/validate_programmability.sql" \
                 "$M1/validation/validate_cleansing_functions.sql"; do
        log "Running ${check#"$REPO_DIR"/}"
        output="$(mariadb "${client_args[@]}" --batch --skip-column-names \
                  "$DATABASE" < "$check")"
        printf '%s\n' "$output" | awk -F'\t' '{printf "    %-55s %s\n", $1, $NF}'
        failures=$((failures + $(printf '%s\n' "$output" | grep -c 'FAIL$' || true)))
    done
    if (( failures > 0 )); then
        log "Validation finished with $failures failing check(s)"
        exit 1
    fi
    log "All validation checks passed"
fi
