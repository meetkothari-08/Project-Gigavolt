#!/usr/bin/env python3
"""Cell-by-cell reconciliation of two Silver databases.

Typical use: compare the Silver layer rebuilt from raw CSVs
(``sql/deploy.sh --raw-dir``) with a reference copy of production Silver,
restored into another schema from a seed dump.

    python tools/compare_silver.py --candidate gigavolt --reference gigavolt_prod
    python tools/compare_silver.py --candidate gigavolt --reference gigavolt_prod --apply-fixes

``--apply-fixes`` first applies the documented production data-quality
corrections to the reference values (see docs/data-platform.md), so the only
remaining differences are genuine rule differences.

Connection settings: MARIADB_HOST / MARIADB_PORT / MARIADB_USER / MARIADB_PASSWORD,
or MARIADB_SOCKET for a local socket.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import pymysql
import pymysql.cursors

TABLE_KEYS = {
    "customers": "customer_id",
    "equipment": "equipment_id",
    "equipment_models": "model",
    "dispatches": "dispatch_id",
    "parts": "part_id",
    "warranty_claims": "claim_id",
}
SKIP_COLUMNS = {"full_service_context"}  # generated from the other columns


def clean_text(value: str) -> str | None:
    """Python mirror of the SQL clean_text() function."""
    value = re.sub(r" +", " ", re.sub(r"<[^>]+>", "", value.replace("\r", ""))).strip()
    return None if value in ("", "NULL", "N/A") else value


def apply_production_fixes(table: str, column: str, value):
    """Documented corrections for defects found in the original production load."""
    if isinstance(value, str):
        value = value.replace("\r", "") or None        # CRLF loaded with a '\n' terminator
    if table == "equipment" and column == "location_notes" and value is not None:
        value = clean_text(value)                       # column was never cleansed
    if table == "customers" and column == "zip" and value:
        value = value.zfill(5)                          # leading zeros lost
    if table == "warranty_claims" and column == "denial_reason" and value == "N/A":
        value = None                                    # tag-wrapped 'N/A' survived
    return value


def connect():
    kwargs = {"cursorclass": pymysql.cursors.DictCursor, "user": os.getenv("MARIADB_USER")}
    if os.getenv("MARIADB_SOCKET"):
        kwargs["unix_socket"] = os.environ["MARIADB_SOCKET"]
    else:
        kwargs["host"] = os.getenv("MARIADB_HOST", "127.0.0.1")
        kwargs["port"] = int(os.getenv("MARIADB_PORT", "3306"))
    if os.getenv("MARIADB_PASSWORD"):
        kwargs["password"] = os.environ["MARIADB_PASSWORD"]
    return pymysql.connect(**kwargs)


def fetch(cursor, schema: str, table: str, key: str) -> dict:
    cursor.execute(f"SELECT * FROM `{schema}`.`{table}`")
    return {row[key]: row for row in cursor.fetchall()}


def compare(connection, candidate: str, reference: str, apply_fixes: bool) -> dict:
    report = {"tables": {}, "rows": 0, "cells": 0, "mismatched_cells": 0, "fixed_cells": {}}
    with connection.cursor() as cursor:
        for table, key in TABLE_KEYS.items():
            new = fetch(cursor, candidate, table, key)
            old = fetch(cursor, reference, table, key)
            mismatches = []
            for row_key in old.keys() & new.keys():
                for column, ref_value in old[row_key].items():
                    if column in SKIP_COLUMNS:
                        continue
                    report["cells"] += 1
                    if apply_fixes:
                        fixed = apply_production_fixes(table, column, ref_value)
                        if fixed != ref_value:
                            name = f"{table}.{column}"
                            report["fixed_cells"][name] = report["fixed_cells"].get(name, 0) + 1
                        ref_value = fixed
                    if new[row_key].get(column) != ref_value:
                        mismatches.append((row_key, column, new[row_key].get(column), ref_value))
            report["tables"][table] = {
                "reference_rows": len(old),
                "candidate_rows": len(new),
                "missing_in_candidate": sorted(old.keys() - new.keys())[:10],
                "extra_in_candidate": sorted(new.keys() - old.keys())[:10],
                "mismatched_cells": len(mismatches),
                "examples": mismatches[:5],
            }
            report["rows"] += len(old)
            report["mismatched_cells"] += len(mismatches)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidate", required=True, help="schema to check (e.g. gigavolt)")
    parser.add_argument("--reference", required=True, help="schema holding reference Silver")
    parser.add_argument("--apply-fixes", action="store_true",
                        help="apply documented production fixes to reference values first")
    args = parser.parse_args()

    report = compare(connect(), args.candidate, args.reference, args.apply_fixes)
    for table, stats in report["tables"].items():
        print(f"{table:17s} rows {stats['reference_rows']:>5} | "
              f"mismatched cells {stats['mismatched_cells']:>4} | "
              f"missing {len(stats['missing_in_candidate'])} | "
              f"extra {len(stats['extra_in_candidate'])}")
        for example in stats["examples"][:3]:
            print(f"    {example}")

    identical = report["cells"] - report["mismatched_cells"]
    share = identical / report["cells"] if report["cells"] else 0
    print(f"\nRows compared: {report['rows']:,} | cells: {report['cells']:,} | "
          f"identical: {identical:,} ({share:.3%})")
    if report["fixed_cells"]:
        print(f"Reference cells corrected by documented fixes: {report['fixed_cells']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
