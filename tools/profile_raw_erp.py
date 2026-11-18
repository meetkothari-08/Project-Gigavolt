#!/usr/bin/env python3
"""Profile the raw (Bronze) ERP CSV extracts and report data-quality issues.

Counts the problems the Silver cleansing step has to resolve: mixed date
formats, duplicate primary keys, HTML fragments, padded whitespace,
inconsistent casing, currency symbols in numeric columns, blank required
fields and foreign keys that point at nothing.

Usage:
    python tools/profile_raw_erp.py data/raw/erp            # text report
    python tools/profile_raw_erp.py data/raw/erp --json     # machine-readable
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

TABLES = {
    "customers": "customer_id",
    "equipment": "equipment_id",
    "dispatches": "dispatch_id",
    "parts": "part_id",
    "warranty_claims": "claim_id",
}

FOREIGN_KEYS = [
    ("equipment", "customer_id", "customers"),
    ("dispatches", "equipment_id", "equipment"),
    ("warranty_claims", "equipment_id", "equipment"),
    ("warranty_claims", "dispatch_id", "dispatches"),
    ("warranty_claims", "part_id", "parts"),
]

DATE_COLUMNS = {
    "customers": ["created_date"],
    "equipment": ["install_date", "warranty_expiration"],
    "dispatches": ["dispatch_date"],
    "warranty_claims": ["claim_date"],
}

NUMERIC_COLUMNS = {
    "equipment": ["capacity_kw"],
    "dispatches": ["hours_spent", "labor_cost"],
    "parts": ["unit_cost", "unit_price", "stock_quantity", "reorder_level"],
    "warranty_claims": ["claim_amount", "approved_amount"],
}

CATEGORICAL_COLUMNS = {
    "customers": ["status"],
    "equipment": ["status"],
    "dispatches": ["status", "service_type"],
    "warranty_claims": ["status"],
}

DATE_PATTERNS = {
    "YYYY-MM-DD": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "ISO-8601 timestamp": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?$"),
    "MM-DD-YYYY": re.compile(r"^\d{2}-\d{2}-\d{4}$"),
    "MM/DD/YYYY": re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$"),
    "YYYY/MM/DD": re.compile(r"^\d{4}/\d{2}/\d{2}$"),
    "Mon DD, YYYY": re.compile(r"^[A-Za-z]{3,9} \d{1,2}, \d{4}$"),
    "DD-Mon-YYYY": re.compile(r"^\d{1,2}-[A-Za-z]{3}-\d{4}$"),
}

HTML_TAG = re.compile(r"<[^>]+>|&[a-z]+;|&#\d+;", re.IGNORECASE)
CLEAN_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def read_table(directory: Path, table: str) -> list[dict[str, str]]:
    path = directory / f"{table}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing extract: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def classify_date(value: str) -> str:
    for label, pattern in DATE_PATTERNS.items():
        if pattern.match(value):
            return label
    return "other"


def profile_table(table: str, rows: list[dict[str, str]]) -> dict:
    key = TABLES[table]
    keys = [row.get(key, "").strip() for row in rows]
    key_counts = Counter(k for k in keys if k)

    report: dict = {
        "rows": len(rows),
        "distinct_keys": len(key_counts),
        "duplicate_key_rows": sum(c - 1 for c in key_counts.values() if c > 1),
        "blank_keys": sum(1 for k in keys if not k),
        "cells_with_html": 0,
        "cells_with_padding": 0,
        "date_formats": {},
        "non_numeric_values": {},
        "casing_variants": {},
    }

    for row in rows:
        for value in row.values():
            if value is None:
                continue
            if HTML_TAG.search(value):
                report["cells_with_html"] += 1
            if value != value.strip() or "  " in value:
                report["cells_with_padding"] += 1

    for column in DATE_COLUMNS.get(table, []):
        formats = Counter(
            classify_date(row[column].strip())
            for row in rows
            if row.get(column, "").strip()
        )
        report["date_formats"][column] = dict(formats.most_common())

    for column in NUMERIC_COLUMNS.get(table, []):
        dirty = [
            row[column]
            for row in rows
            if row.get(column, "").strip()
            and not CLEAN_NUMBER.match(row[column].strip())
        ]
        if dirty:
            report["non_numeric_values"][column] = {
                "count": len(dirty),
                "examples": sorted(set(dirty))[:5],
            }

    for column in CATEGORICAL_COLUMNS.get(table, []):
        variants: dict[str, set[str]] = {}
        for row in rows:
            raw = (row.get(column) or "").strip()
            if raw:
                variants.setdefault(raw.lower(), set()).add(raw)
        inconsistent = {k: sorted(v) for k, v in variants.items() if len(v) > 1}
        if inconsistent:
            report["casing_variants"][column] = inconsistent

    return report


def profile_foreign_keys(data: dict[str, list[dict[str, str]]]) -> dict:
    results = {}
    for child, column, parent in FOREIGN_KEYS:
        parent_keys = {row[TABLES[parent]].strip() for row in data[parent]}
        values = [(row.get(column) or "").strip() for row in data[child]]
        missing = [v for v in values if v and v not in parent_keys]
        results[f"{child}.{column} -> {parent}"] = {
            "blank": sum(1 for v in values if not v),
            "orphaned": len(missing),
            "examples": sorted(set(missing))[:5],
        }
    return results


def print_report(report: dict) -> None:
    for table, stats in report["tables"].items():
        print(f"\n== {table} ({stats['rows']} rows, {stats['distinct_keys']} distinct keys)")
        print(f"   duplicate key rows : {stats['duplicate_key_rows']}")
        print(f"   blank keys         : {stats['blank_keys']}")
        print(f"   cells with HTML    : {stats['cells_with_html']}")
        print(f"   padded cells       : {stats['cells_with_padding']}")
        for column, formats in stats["date_formats"].items():
            print(f"   date formats [{column}]: {formats}")
        for column, info in stats["non_numeric_values"].items():
            print(f"   non-numeric [{column}]: {info['count']} e.g. {info['examples']}")
        for column, variants in stats["casing_variants"].items():
            print(f"   casing variants [{column}]: {len(variants)} values, e.g. "
                  f"{next(iter(variants.values()))}")

    print("\n== foreign keys")
    for relation, info in report["foreign_keys"].items():
        print(f"   {relation:45s} orphaned={info['orphaned']:<5} blank={info['blank']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path, help="Directory holding the five raw CSVs")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args()

    data = {table: read_table(args.directory, table) for table in TABLES}
    report = {
        "tables": {table: profile_table(table, rows) for table, rows in data.items()},
        "foreign_keys": profile_foreign_keys(data),
    }

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
