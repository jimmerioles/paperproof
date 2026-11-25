# Security policy

Paperproof handles documents that may contain personal and financial data. Do not open a public issue for a vulnerability.

## Reporting

Use GitHub private vulnerability reporting:

https://github.com/jimmerioles/paperproof/security/advisories/new

Include:

- the affected commit,
- a reproduction or proof of concept,
- the impact,
- whether customer data could be exposed,
- any suggested fix.

I aim to acknowledge a report within three business days. This is a small project, so there is no paid bounty.

## In scope

- A citation shown without passing `verify_quote`.
- Authentication or authorization bypass once auth exists.
- Path traversal, SSRF, XSS, or CSRF.
- Prompt injection that persists a value without human review.
- Cross-document or cross-tenant data leakage.
- Secrets exposed in logs or build artifacts.

## Out of scope

- Denial of service from an intentionally huge or malformed PDF. Report it if it is cheap to trigger.
- Vulnerabilities in third-party dependencies that have no exploit path in Paperproof. Open a normal issue or a Dependabot PR.
- The absence of a feature that is already listed as a known gap in `docs/PRODUCTION_READINESS.md`.
