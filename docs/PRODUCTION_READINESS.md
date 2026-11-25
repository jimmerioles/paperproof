# Production readiness

This is the gate document. The roadmap says what to build and in what order. This file says whether the result is safe to put in front of a design partner or a paying customer.

Status values:

- **Done**: implemented and covered by a test or a repeatable check.
- **Partial**: exists, but does not meet the gate.
- **Missing**: not built.
- **N/A**: not required for this stage.

Current verdict: **demo-ready, not pilot-ready**.

## Correctness and evals

| Gate | Pilot | GA | Status | Evidence |
| --- | --- | --- | --- | --- |
| A quote is never shown unless it exists in the PDF text layer | Yes | Yes | Done | `extract/verify.py`, `tests/test_verify.py` |
| Exact and fuzzy matches are distinguished in the UI | Yes | Yes | Done | `extract/service.py`, `document.html` |
| Printed page and PDF page are both tracked | Yes | Yes | Done | `ingest/pdf.py`, `presenters.py` |
| Scanned pages are OCR'd locally | Yes | Yes | Done | `ingest/ocr.py`, `tests/test_ocr.py` |
| OCR confidence is visible per page | Yes | Yes | Done | Document banner, source view, `ocr-pill` |
| Synthetic golden set passes in CI | Yes | Yes | Done | `evals/cases.jsonl`, CI |
| 200+ labeled fields from real leases | Yes | Yes | Missing | No real corpus yet |
| Per-field accuracy, precision, recall, and false confidence | Yes | Yes | Missing | Aggregate only today |
| LLM mode evaluated against a real provider | Yes | Yes | Partial | Mock transport tests only |
| Prompt and model version stored per extraction | Yes | Yes | Partial | Model in audit meta, prompt is not versioned |
| Regression gate fails on a wrong answer or unverified citation | Yes | Yes | Done | `paperproof eval`, CI |
| Abstention is measured, not just counted | Yes | Yes | Partial | Counted in the eval, not per field |
| Citation support is labeled by a human | Yes | Yes | Missing | Existence is verified, support is not scored |

## Security

| Gate | Pilot | GA | Status | Evidence |
| --- | --- | --- | --- | --- |
| Authentication on every route | Yes | Yes | Done | `api/auth_middleware.py` |
| CSRF protection on state-changing forms | Yes | Yes | Done | `csrf_protect`, hidden tokens |
| Authorization and tenant isolation | No | Yes | Missing | Single admin |
| Upload size limits | Yes | Yes | Done | `max_upload_mb` |
| Upload content validation | Yes | Yes | Partial | Suffix check plus parser failure |
| Parser isolation, timeouts, and memory limits | Yes | Yes | Missing | In-process parsing |
| Malware scanning for uploads | No | Yes | Missing | Not implemented |
| Rate limiting | Yes | Yes | Partial | Login lockout only, in memory |
| Secrets kept out of the repo | Yes | Yes | Partial | `.env`, 0600 session secret file, no vault |
| Dependency vulnerability scan in CI | Yes | Yes | Missing | `pip-audit` or equivalent not wired |
| CSP and security headers | Yes | Yes | Done | `api/factory.py` middleware |
| TLS in front of the app | Yes | Yes | Missing | Local HTTP only |
| Session cookie hardening | Yes | Yes | Done | HttpOnly, SameSite=Lax, Secure in prod |
| Audit log tamper evidence | No | Yes | Partial | Append-only table, no hash chain |
| Prompt injection containment | Yes | Yes | Partial | No tools, verifier gate, human review |

## Privacy and data

| Gate | Pilot | GA | Status | Evidence |
| --- | --- | --- | --- | --- |
| Retention policy documented and enforced | Yes | Yes | Missing | No delete or expiry |
| Delete a document and its derivatives | Yes | Yes | Missing | No route or command |
| Export a document and its extractions | Yes | Yes | Missing | No export |
| Encryption in transit | Yes | Yes | Missing | No TLS deployment |
| Encryption at rest | No | Yes | Missing | Plain SQLite and files |
| LLM data flow documented per provider | Yes | Yes | Partial | `docs/ARCHITECTURE.md` |
| Subprocessor list | No | Yes | Missing | None |
| Customer data can stay on a local model | No | Yes | Partial | OpenAI-compatible interface, no packaged local model |
| Backups encrypted | No | Yes | Missing | No backup system |

## Reliability and operations

| Gate | Pilot | GA | Status | Evidence |
| --- | --- | --- | --- | --- |
| Backup command | Yes | Yes | Missing | None |
| Restore drill with matching counts | Yes | Yes | Missing | None |
| Health check covers DB and disk | Yes | Yes | Partial | `/healthz` counts only |
| Schema migrations with versioning | Yes | Yes | Partial | `user_version` exists, only version 1 |
| Timeouts and retries for external calls | Yes | Yes | Partial | LLM only |
| Idempotent ingestion and extraction | Yes | Yes | Done | SHA dedupe, upsert |
| Background queue for large documents | No | Yes | Missing | Synchronous requests |
| Graceful shutdown | Yes | Yes | Partial | Uvicorn default |
| Rollback path for a bad deploy | Yes | Yes | Missing | No deploy yet |
| Structured logs | Yes | Yes | Missing | Plain uvicorn logs |
| Request IDs | Yes | Yes | Missing | None |
| Error tracking | Yes | Yes | Missing | None |
| Metrics and dashboards | No | Yes | Missing | None |
| LLM latency and cost tracking | Yes | Yes | Partial | Tokens in metadata, not surfaced |
| Load test and performance budget | Yes | Yes | Missing | None |
| Container build in CI | Yes | Yes | Missing | Dockerfile exists, not built in CI |

## Product and UX

| Gate | Pilot | GA | Status | Evidence |
| --- | --- | --- | --- | --- |
| Review a field against its source page | Yes | Yes | Done | Review desk |
| Approve, reject, and audit decisions | Yes | Yes | Done | Review flow, `audit_log` |
| OCR state visible to the reviewer | Yes | Yes | Done | OCR banner and per-page badge |
| Bulk approve and reject | No | Yes | Missing | One field at a time |
| Reviewer assignment and queues | No | Yes | Missing | None |
| Comments and correction reasons | Yes | Yes | Missing | Reject has no structured reason |
| CSV or Excel export | Yes | Yes | Missing | None |
| Keyboard review path | No | Yes | Partial | Buttons only |
| Accessibility audit | No | Yes | Missing | Semantic HTML, no audit |
| Mobile source view | No | Yes | Partial | Responsive layout exists |
| Median review time under two minutes | Yes | Yes | Missing | Not measured |
| Empty, error, and recovery states | Yes | Yes | Partial | Basic states only |

## Commercial and legal

| Gate | Pilot | GA | Status | Evidence |
| --- | --- | --- | --- | --- |
| Project license is clear | Yes | Yes | Done | FSL-1.1-ALv2 |
| Vendored font licenses included | Yes | Yes | Done | OFL text in `static/fonts` |
| Dependency license audit | Yes | Yes | Partial | No automated check |
| Terms of service | Yes | Yes | Missing | None |
| Privacy policy | Yes | Yes | Missing | None |
| DPA template | No | Yes | Missing | None |
| Subprocessor list | No | Yes | Missing | None |
| Support runbook and channel | Yes | Yes | Missing | None |
| Status page | No | Yes | Missing | None |
| Incident response process | No | Yes | Missing | None |
| Pricing and packaging | No | Yes | Missing | None |
| Security questionnaire pack | No | Yes | Missing | None |

## Pilot launch checklist

- [ ] Every pilot gate above is Done or has a signed exception.
- [ ] A restore drill passed in the last 30 days.
- [ ] TLS is live and HSTS is enabled.
- [ ] Auth is enabled and the default admin password is rotated.
- [ ] The real eval set is green at the required thresholds.
- [ ] A production smoke test uploads, extracts, cites, approves, and exports.
- [ ] Rollback to the previous image is tested.
- [ ] Retention and deletion are configured.
- [ ] A support channel and escalation path are live.
- [ ] The design partner onboarding doc is written.
- [ ] The incident runbook is written.

## Known exceptions

- The Docker image is not built in CI yet. The local environment cannot access the Docker socket, so the image has not been smoke tested. This is tracked in the M1 deployment issue.
- The 35 case eval is synthetic. It proves the loop, not real-world accuracy.
- The hash embedder is lexical. It is deterministic and hermetic, not semantic.
- OCR is local Tesseract only. Cloud fallback and handwriting are not implemented.
- Authentication is one local admin. Roles, SSO, and tenant isolation are not built.
- Login lockout is in memory, so it resets on restart and does not span multiple workers.

## How to update this document

When a gate changes, update the status and add the evidence link in the same pull request. Do not mark a gate Done without a test, a command, or a repeatable manual check. A passing demo is not evidence.
