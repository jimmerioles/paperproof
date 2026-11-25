"""OpenAI-compatible LLM extractor.

Works with OpenAI, OpenRouter, vLLM, Ollama's OpenAI endpoint, and anything
else that implements /chat/completions. The model is never trusted: its quote
goes through the verifier before anything is persisted as a citation.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from pydantic import BaseModel, Field

from paperproof.config import Settings
from paperproof.extract.base import Candidate
from paperproof.extract.templates import FieldSpec
from paperproof.search.retrieve import Hit

JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class LLMAnswer(BaseModel):
    value: Any = None
    quote: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    abstained: bool = False
    reason: str | None = None


SYSTEM_PROMPT = """You extract one factual field from a document.

Rules:
- Use only the supplied passages. Never use outside knowledge.
- The quote must be copied verbatim from one passage and must be enough to prove the value.
- Do not paraphrase inside the quote. Preserve capitalization and punctuation.
- If the passages do not state the answer, abstain instead of guessing.
- Return only a JSON object with exactly these keys:
  value, quote, confidence, abstained, reason.
- confidence is a number from 0.0 to 1.0.
"""

TYPE_INSTRUCTIONS = {
    "int": "value must be a JSON number with no units.",
    "money": "value must be a JSON number in dollars with no currency symbol or commas.",
    "enum": "value must be exactly one of the allowed values.",
    "text": "value must be a short string of at most 60 words.",
    "bool": "value must be true or false.",
}


class LLMExtractor:
    name = "llm"

    def __init__(self, settings: Settings) -> None:
        if not settings.llm_base_url:
            raise RuntimeError("LLM extractor selected but PAPERPROOF_LLM_BASE_URL is not set.")
        self.settings = settings
        base = settings.llm_base_url.rstrip("/")
        self.url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        self.client = httpx.Client(timeout=settings.llm_timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        return headers

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(self.url, headers=self._headers(), json=payload)
        if response.status_code == 400 and "response_format" in response.text:
            payload = dict(payload)
            payload.pop("response_format", None)
            response = self.client.post(self.url, headers=self._headers(), json=payload)
        if response.status_code >= 400:
            detail = response.text[:500]
            raise RuntimeError(f"LLM request failed with HTTP {response.status_code}: {detail}")
        return response.json()

    def _messages(
        self,
        spec: FieldSpec,
        doc_title: str,
        hits: list[Hit],
        feedback: str | None,
    ) -> list[dict[str, str]]:
        passages = "\n\n".join(
            f"[passage {index + 1} | PDF page {hit.page_start} | "
            f"section: {hit.heading or 'none'}]\n{hit.text[:1800]}"
            for index, hit in enumerate(hits)
        )
        instructions = TYPE_INSTRUCTIONS[spec.kind]
        if spec.options:
            instructions += f" Allowed values: {', '.join(spec.options)}."
        if spec.unit:
            instructions += f" Unit: {spec.unit}."
        user = f"""Document: {doc_title}
Field: {spec.label}
Question: {spec.question}
Answer type: {spec.kind}. {instructions}

Passages:
{passages or "(none)"}

Return the JSON object now."""
        if feedback:
            user += f"\n\nCorrection from the verifier: {feedback}"
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    def _coerce(self, spec: FieldSpec, value: Any) -> Any:
        if spec.kind == "int":
            if isinstance(value, bool):
                raise ValueError("boolean is not an integer")
            return round(float(str(value).replace(",", "").replace("$", "")))
        if spec.kind == "money":
            return float(str(value).replace(",", "").replace("$", ""))
        if spec.kind == "enum":
            candidate = str(value).strip().lower().replace(" ", "_").replace("-", "_")
            if spec.options and candidate not in spec.options:
                raise ValueError(f"{candidate!r} is not one of {spec.options}")
            return candidate
        if spec.kind == "text":
            text = str(value).strip()
            if not text:
                raise ValueError("empty text")
            return text[:600]
        if spec.kind == "bool":
            if isinstance(value, bool):
                return value
            lowered = str(value).strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
            raise ValueError(f"{value!r} is not a boolean")
        raise ValueError(f"unsupported kind {spec.kind}")

    def extract(
        self,
        spec: FieldSpec,
        doc_title: str,
        hits: list[Hit],
        feedback: str | None = None,
    ) -> Candidate:
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": self._messages(spec, doc_title, hits, feedback),
            "temperature": self.settings.llm_temperature,
            "response_format": {"type": "json_object"},
        }
        data = self._post(payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected LLM response shape: {str(data)[:300]}") from exc

        match = JSON_BLOCK.search(content or "")
        if not match:
            raise RuntimeError(f"LLM did not return JSON: {str(content)[:300]}")
        try:
            answer = LLMAnswer.model_validate_json(match.group(0))
        except ValueError as exc:
            raise RuntimeError(f"Invalid LLM JSON: {str(content)[:300]}") from exc

        usage = data.get("usage") or {}
        meta = {
            "model": self.settings.llm_model,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }

        if answer.abstained:
            return Candidate(abstained=True, reason=answer.reason or "Model abstained.", meta=meta)
        if not answer.quote:
            return Candidate(abstained=True, reason="Model returned no quote.", meta=meta)

        try:
            value = self._coerce(spec, answer.value)
        except (TypeError, ValueError) as exc:
            return Candidate(
                abstained=True,
                reason=f"Model returned an unusable value: {exc}",
                meta=meta,
            )

        return Candidate(
            value=value,
            quote=answer.quote.strip(),
            confidence=float(answer.confidence),
            reason=answer.reason,
            meta=meta,
        )

    def close(self) -> None:
        self.client.close()
