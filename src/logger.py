"""Logging setup for AI assistant backend."""

from __future__ import annotations

import logging


def setup_logging(log_level: str) -> None:
    """Configure root logger once at process startup."""
    level = getattr(logging, (log_level or "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
