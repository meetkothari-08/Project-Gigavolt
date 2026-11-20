#!/usr/bin/env bash
# =============================================================================
# Load analytics_columnstore in small batches until it holds TARGET_COPIES
# copies of the 4,941-row analytics_base table (default 100 -> 494,100 rows).
#
# Each batch adds up to BATCH_COPIES copies, so every INSERT stays small on a
# t3.micro node and progress is visible:
#
#   Current rows: 469395. Loading next batch...
#   | columnstore_rows | copies_added_this_batch |
#   |           494100 |                       5 |
#   SUCCESS: ColumnStore reached 494100 rows.
#
# Run on gigavolt-3 after sql/columnstore_analytics.sql has created the tables.
#   MARIADB_CMD="sudo mariadb" scripts/load_columnstore.sh
# =============================================================================
set -euo pipefail

MARIADB_CMD=${MARIADB_CMD:-"sudo mariadb"}
DATABASE=${DATABASE:-gigavolt}
TARGET_COPIES=${TARGET_COPIES:-100}
BATCH_COPIES=${BATCH_COPIES:-5}
TABLE=${TABLE:-analytics_columnstore}

sql() { $MARIADB_CMD --batch --skip-column-names "$DATABASE" -e "SET SESSION wsrep_on = OFF; $1"; }

base_rows=$(sql "SELECT COUNT(*) FROM analytics_base")
[[ "$base_rows" -gt 0 ]] || { echo "analytics_base is empty; run sql/columnstore_analytics.sql first" >&2; exit 1; }
target_rows=$(( base_rows * TARGET_COPIES ))

while :; do
    loaded_copies=$(sql "SELECT COALESCE(MAX(copy_no), 0) FROM $TABLE")
    current_rows=$(sql "SELECT COUNT(*) FROM $TABLE")
    if (( current_rows >= target_rows )); then
        echo "SUCCESS: ColumnStore reached $current_rows rows."
        break
    fi

    echo "Current rows: $current_rows. Loading next batch..."
    first=$(( loaded_copies + 1 ))
    last=$(( loaded_copies + BATCH_COPIES ))
    (( last > TARGET_COPIES )) && last=$TARGET_COPIES

    $MARIADB_CMD --table "$DATABASE" -e "
        SET SESSION wsrep_on = OFF;
        INSERT INTO $TABLE
        SELECT s.seq, b.dispatch_id, b.equipment_id, b.model, b.service_type,
               b.dispatch_date, b.hours_spent, b.labor_cost, b.total_claim_amount
        FROM seq_${first}_to_${last} s CROSS JOIN analytics_base b;
        SELECT COUNT(*) AS columnstore_rows,
               $(( last - first + 1 )) AS copies_added_this_batch
        FROM $TABLE;"
done
