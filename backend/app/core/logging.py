import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{8,})|(Bearer\s+\S+)", re.IGNORECASE)


def _redact(value: str) -> str:
    return _SECRET.sub("[redacted]", value)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, limited to observable fields.

    Private model reasoning is not a log field. Callers add request or
    workflow identifiers through the standard `extra` mapping.
    """

    _EXTRA_FIELDS = (
        "request_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self._EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = _redact(self.formatException(record.exc_info))
        redacted = {
            key: _redact(item) if isinstance(item, str) else item for key, item in payload.items()
        }
        return json.dumps(redacted, default=str)


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
