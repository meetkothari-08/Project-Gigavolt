"""Logging configuration shared by the command-line entry points."""

from __future__ import annotations

import logging

from gigavolt.config import get_settings


def configure_logging(log_name: str, level: int = logging.INFO) -> None:
    """Log to stderr and to ``$GIGAVOLT_LOG_DIR/<log_name>``."""
    log_dir = get_settings().paths.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.FileHandler(log_dir / log_name), logging.StreamHandler()],
    )
