# Roadmap

Paperproof is a document intelligence review desk with a hard trust boundary: a quote is shown only after it is verified against the source page.

This roadmap sequences work by risk, not by feature appeal. The goal is a design partner pilot on real leases before building scale. Each phase has an exit gate. Do not start the next phase until the gate is met.

## Current state

Working today:

- Verified citations with exact and fuzzy matching, printed page labels, and highlight boxes.
- Review desk with approve and reject, source viewer, search, and audit log.
- Single-admin authentication with signed sessions, CSRF, and login lockout.
- Local OCR for scanned leases with per-page confidence and a visible low-confidence warning.
- Backup, restore, and a restore drill that runs in CI.
- JSON request logs, request IDs, health checks, and per-field cost tracking.
- Docker Compose deployment with Caddy TLS, healthchecks, upgrade, and rollback docs.
- Private case-set eval importer with per-field precision, recall, support labels, and a CSV report.
- Offline rule extractor and an OpenAI-compatible LLM extractor.
- 35 case synthetic golden set, 72 tests, CI, and a source-available license.

Missing for a pilot:

- Neural embeddings.
- An eval set built from real documents.

## Production definition

Production ready for a **design partner pilot** means all of these are true:

| Area | Gate |
| --- | --- |
| Correctness | 200+ labeled fields from real leases. 100% citation existence, 98% citation support, 90% field accuracy, zero unverified citations shown. |
| Security | Authentication, CSRF, and authorization on every route. Upload limits and parser isolation. No high or critical findings in a security review. |
| Privacy | Documented LLM data flow. Retention and deletion. Encryption in transit. A subprocessor list before the first external customer. |
| Reliability | TLS deployment. Backups with a passing restore drill. Timeouts, retries, and idempotent jobs. A rollback path. |
| Observability | JSON logs, request IDs, extraction duration, model and cost tracking, and an audit export. |
| UX | A reviewer can complete a document in under two minutes median. Clear empty, error, and OCR states. A keyboard path. |
| Commercial | Terms, privacy policy, DPA template, license compliance, and a support runbook. |

General availability adds multi-tenant isolation, SSO, billing, a penetration test, and a support organization. Those are Phase 3.

See [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md) for the line-by-line checklist and current status.

## Phase 1: Pilot-ready (now)

**Outcome:** three design partners can upload real leases, including scans, and a reviewer can check and approve every field without a demo script.

**Exit gate:**

- 3 design partners, 60 real documents, 200+ labeled fields.
- OCR covers scans with a visible confidence flag.
- Authentication and CSRF protect every route.
- TLS deployment with backups and a passing restore drill.
- 98% citation support, 90% field accuracy, zero unverified citations.
- p95 extraction under two minutes for a 50 page document.

**Work in the M1 milestone:**

1. [x] OCR pipeline for scanned PDFs.
2. [ ] Neural embeddings behind the `Embedder` protocol.
3. [ ] Real-document eval set with per-field metrics.
4. [x] Authentication, sessions, and CSRF.
5. [x] Backup and restore drill.
6. [x] Structured logs, request IDs, and cost tracking.
7. [x] Deployment bundle with TLS and healthchecks.

## Phase 2: Team-ready

**Outcome:** one team uses Paperproof weekly for one document type.

**Exit gate:**

- 1 team, 500 documents, 3 weekly active reviewers.
- Median review time under two minutes per document.
- Assignment, bulk review, comments, and CSV export.
- End-to-end browser tests and a load test.
- Correction feedback feeds the eval set.
- p95 document page load under 1.5 seconds.

**Work:**

- Reviewer assignment and queues.
- Bulk approve and reject with keyboard shortcuts.
- CSV and Excel export, plus audit export.
- Correction reasons and an eval feedback loop.
- Document deletion, retention, and export.
- Prompt and model registry with run comparison.
- Playwright end-to-end suite.
- Load test and performance budget.
- Page render cache and pagination.

## Phase 3: Commercial launch

**Outcome:** five organizations, assisted onboarding, and a support motion.

**Exit gate:**

- Multi-tenant isolation tested across organizations.
- SSO and SCIM for at least one enterprise customer.
- Security review and penetration test with no high or critical findings.
- DPA, privacy policy, subprocessor list, and retention policy.
- Billing, usage limits, and an admin console.
- Status page, incident runbook, and support SLA.

**Work:**

- Organizations, roles, and row-level isolation.
- Postgres and pgvector migration.
- Object storage and a background worker queue.
- SSO, SAML, and SCIM.
- Billing and usage metering.
- Security review and remediation.
- Legal and procurement pack.
- Status page and support tooling.

## Not now

These are deliberately deferred. Revisit them only when a customer or a gate demands it.

- Chat over documents.
- Mobile app.
- E-signature.
- Custom model training.
- Visual workflow builder.
- SOC 2 before a customer asks.
- Billing before a pilot converts.
- Multi-tenant before a second team is paying.
- A Kubernetes deployment before a single VM is saturated.

## Decisions needed

Write an ADR in `docs/adr/` before making these choices. Each one is expensive to reverse.

1. **Deployment target.** Single-tenant Docker Compose on a small VM, or a managed platform. Recommendation: Compose for the pilot.
2. **LLM data policy.** Which provider can see customer documents, and under what terms. Recommendation: provider-agnostic, local model available, explicit data terms per customer.
3. **Embedding model.** Local fastembed or an API. Recommendation: local, so tests and pilots work offline.
4. **Retention default.** Recommendation: 90 days for abandoned uploads, configurable, with immediate delete on request.

## How to work on this

The unit of work is one issue that fits one focused session.

1. Pull and run `make check`.
2. Pick one `status:ready` issue from the active milestone.
3. Branch from `main`, implement the smallest change, add the test or eval case.
4. Run `make check`, open a PR, merge when green.
5. Leave a short note on the issue: what changed, what is next, what is blocked.

Keep at most three issues in `status:ready` at a time. If an issue needs more than three sessions, split it.

See [docs/WORKFLOW.md](docs/WORKFLOW.md) for the session ritual, issue quality bar, and weekly review.
