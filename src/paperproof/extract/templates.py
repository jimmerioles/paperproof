"""The lease template: what we extract and how we ask for it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

FieldKind = Literal["bool", "int", "money", "text", "enum"]


class FieldSpec(BaseModel):
    name: str
    label: str
    kind: FieldKind
    question: str
    hints: list[str] = []
    options: list[str] | None = None
    unit: str | None = None

    def search_query(self) -> str:
        return " ".join([self.question, *self.hints])


class Template(BaseModel):
    id: str
    name: str
    description: str
    fields: list[FieldSpec]


LEASE = Template(
    id="lease",
    name="Residential lease",
    description="Core commercial terms from a residential lease agreement.",
    fields=[
        FieldSpec(
            name="term_months",
            label="Term",
            kind="int",
            unit="months",
            question="How long is the initial lease term in months?",
            hints=["term", "months", "years", "commencement", "expiration"],
        ),
        FieldSpec(
            name="monthly_rent",
            label="Monthly rent",
            kind="money",
            question="What is the monthly rent amount?",
            hints=["monthly rent", "rent", "due", "payment"],
        ),
        FieldSpec(
            name="security_deposit",
            label="Security deposit",
            kind="money",
            question="What is the security deposit amount?",
            hints=["security deposit", "deposit", "held", "return"],
        ),
        FieldSpec(
            name="notice_days",
            label="Termination notice",
            kind="int",
            unit="days",
            question=(
                "How many days of written notice are required to terminate or not renew the lease?"
            ),
            hints=["notice", "days", "written", "terminate", "end of the term"],
        ),
        FieldSpec(
            name="subletting",
            label="Subletting",
            kind="enum",
            question=(
                "Does the lease prohibit subletting, allow it only with consent, "
                "or allow it without consent?"
            ),
            hints=["sublet", "sublease", "assign", "transfer", "consent"],
            options=["prohibited", "allowed_with_consent", "allowed"],
        ),
        FieldSpec(
            name="renewal_option",
            label="Renewal option",
            kind="text",
            question="What renewal or extension option does the tenant have?",
            hints=["renew", "renewal", "extend", "extension", "option"],
        ),
        FieldSpec(
            name="late_fee",
            label="Late fee",
            kind="money",
            question="What late fee applies when rent is paid late?",
            hints=["late fee", "late charge", "past due"],
        ),
    ],
)

TEMPLATES: dict[str, Template] = {LEASE.id: LEASE}


def get_template(template_id: str) -> Template:
    try:
        return TEMPLATES[template_id]
    except KeyError as exc:
        raise ValueError(
            f"Unknown template {template_id!r}. Available: {sorted(TEMPLATES)}"
        ) from exc
