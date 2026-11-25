"""JSON logging and request-scoped context."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime

REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="-")
_JSON_MARKER = "_paperproof_json"


def get_request_id() -> str:
    return REQUEST_ID.get()


def set_request_id(value: str) -> Token[str]:
    return REQUEST_ID.set(value)


def reset_request_id(token: Token[str]) -> None:
    REQUEST_ID.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = get_request_id()
        if request_id and request_id != "-":
            payload["request_id"] = request_id
        for key in (
            "method",
            "path",
            "status",
            "duration_ms",
            "provider",
            "model",
            "cost_usd",
            "user",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)[:4000]
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(getattr(handler, _JSON_MARKER, False) for handler in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    setattr(handler, _JSON_MARKER, True)
    root.handlers = [handler]
    root.setLevel(level.upper())

    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
