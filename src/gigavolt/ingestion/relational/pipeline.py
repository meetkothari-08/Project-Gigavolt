"""Relational ingestion pipeline: detect -> validate -> record state -> audit checkpoint.

    python -m gigavolt.ingestion.relational.pipeline --dry-run
    python -m gigavolt.ingestion.relational.pipeline
"""

from __future__ import annotations

import argparse
import logging

from gigavolt.ingestion.relational.detector import AUDIT_CHECKPOINT, RelationalDetector
from gigavolt.ingestion.relational.validator import RelationalValidator
from gigavolt.logging_setup import configure_logging

logger = logging.getLogger("gigavolt.relational_pipeline")


class RelationalPipeline:
    """Coordinate relational change detection, validation and state tracking."""

    def __init__(self, detector: RelationalDetector | None = None,
                 validator: RelationalValidator | None = None):
        self.detector = detector or RelationalDetector()
        self.state = self.detector.state
        self.validator = validator or RelationalValidator()

    def run(self, dry_run: bool = False) -> dict:
        summary = {
            "new": 0,
            "modified": 0,
            "unchanged": 0,
            "processed": 0,
            "invalid": 0,
            "failed": 0,
            "audit_events": 0,
        }

        logger.info("Starting relational pipeline (dry_run=%s)", dry_run)

        try:
            # Stage 1: detect changed rows.
            changes = self.detector.detect_all_changes()

            for table_name, records in changes.items():
                scanned = self.detector.scanned.get(table_name, len(records))
                summary["unchanged"] += scanned - len(records)
                logger.info("Detected %s candidate changes in %s", len(records), table_name)

                for item in records:
                    record_id = item["record_id"]
                    summary["new" if item["change_type"] == "NEW" else "modified"] += 1

                    # Stage 2: validate.
                    validation = self.validator.validate(table_name, item["record"])
                    if not validation["valid"]:
                        summary["invalid"] += 1
                        logger.error(
                            "Invalid record: %s | ID: %s | Errors: %s",
                            table_name, record_id, validation["errors"],
                        )
                        continue

                    if dry_run:
                        logger.info("[DRY RUN] Valid %s record: %s", table_name, record_id)
                        continue

                    # Stage 3: record successful processing.
                    try:
                        self.state.save_record(table_name, record_id, item["record_hash"])
                        summary["processed"] += 1
                        logger.info(
                            "Processed %s %s record: %s",
                            item["change_type"], table_name, record_id,
                        )
                    except Exception:
                        summary["failed"] += 1
                        logger.exception("Failed to process %s record: %s", table_name, record_id)

            # Stage 4: dispatch audit events since the last checkpoint.
            audit_events = self.detector.get_new_dispatch_audit_events()
            summary["audit_events"] = len(audit_events)

            if audit_events and not dry_run:
                try:
                    for event in audit_events:
                        logger.info(
                            "Audit event %s | %s | %s",
                            event["audit_id"], event["operation_type"],
                            event["change_description"],
                        )
                    # Advance the checkpoint only after every event was handled.
                    self.state.save_checkpoint(
                        AUDIT_CHECKPOINT, max(event["audit_id"] for event in audit_events)
                    )
                except Exception:
                    summary["failed"] += 1
                    logger.exception("Failed while processing dispatch audit events")

            logger.info("Relational pipeline completed: %s", summary)
            return summary

        finally:
            self.detector.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gigavolt relational ingestion pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect and validate without updating processing state",
    )
    args = parser.parse_args(argv)

    configure_logging("relational_pipeline.log")
    summary = RelationalPipeline().run(dry_run=args.dry_run)
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
