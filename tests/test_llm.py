from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from paperproof.config import Settings
from paperproof.extract.llm import LLMExtractor
from paperproof.extract.templates import LEASE
from paperproof.search.retrieve import Hit


def make_hit(text: str = "The term of this Lease is twenty-four (24) months.") -> Hit:
    return Hit(
        chunk_id=1,
        doc_id="doc_test",
        filename="lease.pdf",
        title="Lease",
        heading="2. Term",
        text=text,
        page_start=3,
        page_end=3,
        score=1.0,
    )


def make_extractor(tmp_path: Path, handler) -> LLMExtractor:
    settings = Settings(
        data_dir=tmp_path,
        llm_base_url="http://llm.test/v1",
        llm_api_key="test-key",
        llm_model="test-model",
    )
    extractor = LLMExtractor(settings)
    extractor.client.close()
    extractor.client = httpx.Client(transport=httpx.MockTransport(handler))
    return extractor


def answer(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "choices": [{"message": {"content": json.dumps(payload)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        },
    )


def test_llm_extracts_and_preserves_quote(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return answer(
            {
                "value": 24,
                "quote": "The term of this Lease is twenty-four (24) months.",
                "confidence": 0.92,
                "abstained": False,
                "reason": None,
            }
        )

    extractor = make_extractor(tmp_path, handler)
    try:
        candidate = extractor.extract(LEASE.fields[0], "Lease", [make_hit()])
    finally:
        extractor.close()
    assert candidate.value == 24
    assert candidate.quote == "The term of this Lease is twenty-four (24) months."
    assert candidate.confidence == 0.92
    assert seen["model"] == "test-model"
    assert seen["response_format"] == {"type": "json_object"}
    messages = seen["messages"]
    assert isinstance(messages, list)
    assert "verbatim" in messages[0]["content"]


def test_llm_abstains_when_document_is_silent(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return answer(
            {
                "value": None,
                "quote": None,
                "confidence": 0.0,
                "abstained": True,
                "reason": "No renewal clause.",
            }
        )

    extractor = make_extractor(tmp_path, handler)
    try:
        candidate = extractor.extract(LEASE.fields[5], "Lease", [make_hit("Nothing here.")])
    finally:
        extractor.close()
    assert candidate.abstained is True
    assert candidate.quote is None
    assert candidate.reason == "No renewal clause."


def test_llm_rejects_invalid_enum_value(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return answer(
            {
                "value": "sometimes",
                "quote": "Tenant may sublet with consent.",
                "confidence": 0.8,
                "abstained": False,
            }
        )

    extractor = make_extractor(tmp_path, handler)
    try:
        candidate = extractor.extract(LEASE.fields[4], "Lease", [make_hit()])
    finally:
        extractor.close()
    assert candidate.abstained is True
    assert "unusable" in (candidate.reason or "")


def test_llm_http_error_raises(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    extractor = make_extractor(tmp_path, handler)
    try:
        with pytest.raises(RuntimeError, match="500"):
            extractor.extract(LEASE.fields[0], "Lease", [make_hit()])
    finally:
        extractor.close()


def test_llm_malformed_json_raises(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    extractor = make_extractor(tmp_path, handler)
    try:
        with pytest.raises(RuntimeError, match="did not return JSON"):
            extractor.extract(LEASE.fields[0], "Lease", [make_hit()])
    finally:
        extractor.close()
