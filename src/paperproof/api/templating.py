"""Jinja environment and display filters."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment
from markupsafe import Markup, escape
from starlette.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"

ENUM_LABELS = {
    "prohibited": "Prohibited",
    "allowed_with_consent": "Allowed with consent",
    "allowed": "Allowed without consent",
}

STATUS_LABELS = {
    "pending": "Ready to review",
    "approved": "Approved",
    "rejected": "Rejected",
    "abstained": "Not addressed",
    "failed": "Unverified",
}


def money(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"${float(str(value)):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def pretty_enum(value: object) -> str:
    return ENUM_LABELS.get(str(value), str(value).replace("_", " ").capitalize())


def status_label(value: object) -> str:
    return STATUS_LABELS.get(str(value), str(value).capitalize())


def human_date(value: object) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return parsed.strftime("%b %-d, %Y")


def highlight(text: object, terms: list[str] | None) -> Markup:
    escaped = str(escape(str(text)))
    if not terms:
        return escape(str(text))
    cleaned = [re.escape(term) for term in terms if term.strip()]
    if not cleaned:
        return escape(str(text))
    pattern = re.compile(
        "(" + "|".join(sorted(cleaned, key=len, reverse=True)) + ")",
        re.IGNORECASE,
    )
    # The source text is escaped above; only the <mark> wrapper is added.
    return Markup(pattern.sub(r"<mark>\1</mark>", escaped))  # noqa: S704


def configure(env: Environment) -> None:
    env.filters["money"] = money
    env.filters["enum_label"] = pretty_enum
    env.filters["status_label"] = status_label
    env.filters["human_date"] = human_date
    env.filters["highlight"] = highlight
    env.globals["app_name"] = "Paperproof"
    env.globals["tagline"] = "Every answer, page-checked."


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
configure(templates.env)
