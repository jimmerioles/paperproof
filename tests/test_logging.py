from __future__ import annotations

import json
import logging

from paperproof.logging import JsonFormatter, reset_request_id, set_request_id


def test_json_formatter_includes_request_id() -> None:
    record = logging.LogRecord(
        "paperproof.test",
        logging.INFO,
        __file__,
        1,
        "processed %s",
        ("document",),
        None,
    )
    record.method = "POST"
    record.path = "/documents"
    record.status = 200
    record.duration_ms = 12.5
    token = set_request_id("req_12345678")
    try:
        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_request_id(token)
    assert payload["level"] == "INFO"
    assert payload["message"] == "processed document"
    assert payload["request_id"] == "req_12345678"
    assert payload["status"] == 200
    assert payload["duration_ms"] == 12.5


def test_json_formatter_omits_empty_request_id() -> None:
    record = logging.LogRecord(
        "paperproof.test",
        logging.INFO,
        __file__,
        1,
        "plain",
        (),
        None,
    )
    payload = json.loads(JsonFormatter().format(record))
    assert "request_id" not in payload
