"""Logging setup for journald-friendly stdout plus rotating local files."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path


def configure_logging(log_file: Path, *, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("shotdeck_updater")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        rotating_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=1_000_000,
            backupCount=5,
        )
        rotating_handler.setLevel(logging.DEBUG)
        rotating_handler.setFormatter(formatter)
        logger.addHandler(rotating_handler)
    except OSError:
        logger.warning("Could not open rotating log file at %s", log_file)

    logger.propagate = False
    return logger
