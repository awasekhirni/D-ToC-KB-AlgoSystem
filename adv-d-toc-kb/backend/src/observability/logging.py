"""Structured logging configuration.

Provides two formatters:

- ``json`` (default): one JSON object per log line, suitable for ingestion
  into ELK, Loki, Datadog, or CloudWatch Logs.
- ``text``: human-readable coloured output for local development.

Usage in application code::

    import logging
    logger = logging.getLogger(__name__)
    logger.info("Routed content", extra={"node_id": str(node_id)})

The structured ``extra`` fields appear at the top level of the JSON object
alongside ``timestamp``, ``level``, ``logger``, and ``message``.

Call ``configure_logging()`` once at process startup (done automatically
in ``api/main.py`` and ``workers/celery_app.py``).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


# ANSI colour codes for the text formatter.
_COLOR_MAP = {
    "DEBUG": "\033[36m",    # cyan
    "INFO": "\033[32m",     # green
    "WARNING": "\033[33m",  # yellow
    "ERROR": "\033[31m",    # red
    "CRITICAL": "\033[35m", # magenta
}
_RESET = "\033[0m"


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record.

    Standard fields: ``timestamp``, ``level``, ``logger``, ``message``,
    plus any ``extra`` keys passed to the log call, plus ``exc_info``
    formatted as a string when an exception is attached.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach structured extras (anything the caller added via extra=...).
        reserved = set(vars(record).keys()) | {"message"}
        for key, value in record.__dict__.items():
            if key in reserved or key.startswith("_"):
                continue
            payload[key] = _safe_json(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable coloured output for development."""

    def format(self, record: logging.LogRecord) -> str:
        color = _COLOR_MAP.get(record.levelname, "")
        ts = datetime.fromtimestamp(
            record.created, tz=timezone.utc
        ).strftime("%H:%M:%S")
        base = (
            f"{color}{ts} {record.levelname:<7}\033[0m "
            f"[{record.name}] {record.getMessage()}"
        )

        # Append extras (excluding standard attrs).
        reserved = set(vars(record).keys())
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in reserved and not k.startswith("_")
        }
        if extras:
            base += "  " + " ".join(f"{k}={v}" for k, v in extras.items())

        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def _safe_json(value: Any) -> Any:
    """Make a value JSON-serialisable; fall back to ``str()``."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def configure_logging(
    level: str = "INFO",
    fmt: str = "json",
) -> None:
    """Configure the root logger once at process startup.

    Args:
        level: Log level name (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``).
        fmt: ``"json"`` or ``"text"``.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if fmt.lower() == "text":
        handler.setFormatter(TextFormatter())
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    # Clear any pre-existing handlers (e.g. uvicorn's) so we own the output.
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric_level)

    # Tame noisy third-party loggers without silencing them entirely.
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "httpx"):
        logging.getLogger(noisy).setLevel(
            logging.DEBUG if numeric_level == logging.DEBUG else logging.WARNING
        )

    # Log a startup banner so we can confirm the formatter took effect.
    boot = logging.getLogger("src.observability")
    boot.info(
        "Logging configured",
        extra={"log_level": level, "log_format": fmt},
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``src.*`` namespace.

    Prefer this over ``logging.getLogger(__name__)`` in modules that
    want consistent namespacing. The returned logger inherits the root
    configuration set by ``configure_logging``.
    """
    return logging.getLogger(name)
