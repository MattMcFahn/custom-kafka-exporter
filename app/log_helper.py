"""Logging help"""

import logging
import sys


def _configure_logging(log_level: str) -> None:
    """Configure root-level structured logging to stdout.

    Args:
        log_level: One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
    """
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
