# Agent guide

This repository is built to be changed safely by coding agents and humans. Read this before editing.

## Commands

```bash
uv sync                     # install
uv run paperproof demo      # seed ./data with the sample corpus
uv run paperproof auth set-password  # create the local admin
uv run paperproof serve     # http://127.0.0.1:8000
uv run pytest               # 60 tests
uv run ruff check .         # lint
uv run ruff format .        # format
uv run pyright              # type check
uv run paperproof eval      # 35 case golden set
make check                  # everything above except serve
```

## Architecture in one screen

```text
api/         FastAPI routes, auth middleware, templates, presenters, static assets
extract/     FieldSpec + Template, RuleExtractor, LLMExtractor, verify_quote, service
ingest/      parse_pdf -> Pages/Words, OCR for scans, chunk_pages, ingest_file
search/      HashingEmbedder, index_chunks, hybrid search with RRF
auth.py      password hashing, signed sessions, CSRF, login limiter
db.py        schema, connection helpers, audit()
evaluation.py golden-set runner
samples.py   synthetic lease PDFs
```

The web app is server-rendered. No Node build step. CSS and JS live in `api/static/`. The page viewer overlays percentage-positioned highlight boxes on a PNG rendered by `pypdfium2`.

## Invariants

1. **Never display an unverified quote.** `extract/service.py` must call `verify_quote` before persisting a quote. If verification fails, the extraction is `failed` and the UI shows no citation.
2. **Persist the verified quote.** Store `Verification.quote` (the text found in the PDF), not the model's raw quote, so the citation is literally the source text.
3. **Boxes are PDF points until the presenter.** `verify.py` returns point coordinates. `presenters.boxes_percent` converts them for CSS. Do not mix coordinate systems.
4. **Template order is UI order.** `document_view` sorts extraction rows by `Template.fields`. Do not order by UUID or insertion time.
5. **Every mutation writes an audit event.** Ingestion, extraction runs, and review decisions call `db.audit`.
6. **Abstention is a valid outcome.** Do not fill a missing clause with a guess. A scanned document produces abstained rows with a clear reason.
7. **Schema changes need a migration.** Bump `SCHEMA_VERSION` and add the migration. Do not silently mutate existing databases.
8. **Tests must not call external services.** Use `httpx.MockTransport` for the LLM. The default embedder is deterministic.
9. **No em dashes in prose.** Use commas, colons, or separate sentences. This applies to docs, comments, UI copy, and commit messages.
10. **Keep the trust boundary small.** New extraction paths must return `Candidate` and go through `extract_document`. Do not add a second path to the database.
11. **Keep the license story accurate.** The project is source-available under FSL-1.1-ALv2, not OSI open source. Do not relabel it as MIT or "open source" in docs, package metadata, or the UI.
12. **OCR text is untrusted.** Page text recovered by OCR can contain mistakes. Verify quotes against that text, expose the confidence, and never hide the OCR state from the reviewer.
13. **Do not bypass authentication or CSRF.** Every state-changing route depends on `csrf_protect`. Do not disable auth outside `PAPERPROOF_ENV=dev`, and do not add a new POST route without the dependency.

## Where to change things

| Task | File |
| --- | --- |
| Add a lease field | `extract/templates.py`, then rules and samples/evals |
| Improve a rule parser | `extract/rules.py` |
| Change the LLM prompt | `extract/llm.py` |
| Fix citation matching | `extract/verify.py` (add a test first) |
| Change retrieval fusion | `search/retrieve.py` |
| Add a route | `api/routes.py` |
| Change the review UI | `api/templates/document.html`, `api/static/app.css`, `api/static/app.js` |
| Add a CLI command | `cli.py` |
| Change authentication | `auth.py`, `api/auth_middleware.py`, `api/auth_routes.py` |
| Add a POST route | `api/routes.py`, include `Depends(csrf_protect)` and a CSRF hidden field |
| Add a golden case | `evals/cases.jsonl` |
| Change the schema | `db.py` plus a migration |

## Testing rules

- Run `make check` before calling work done.
- Add a failing unit test for verifier changes. The verifier is the product.
- Add an eval case when you change extraction behavior.
- API tests use a temporary data directory. Never write to `./data` from tests.
- Keep the golden set honest. If a rule gets worse, the eval must fail.

## Style

- Python 3.12+ syntax, full type hints, `from __future__ import annotations`.
- Pydantic v2 for boundaries and structured model output.
- SQL is parameterized. FTS queries are tokenized and quoted.
- Server-rendered HTML. Jinja autoescape stays on. No inline scripts (CSP forbids them).
- UI copy is plain and active: "Approve", "Reject", "Not addressed", "Run extraction again".
- New colors go through the CSS variables in `api/static/app.css`. The accent red is reserved for citations and active state.

## Backlog and roadmap

- `ROADMAP.md` is the source of truth for phase and order.
- `docs/PRODUCTION_READINESS.md` is the gate. Do not mark a gate Done without evidence.
- Pick one `status:ready` issue from the active milestone. Keep at most three ready at a time.
- Split an issue if it needs more than three sessions.
- Record expensive, hard-to-reverse choices in `docs/adr/`.
- Update the readiness checklist in the same pull request when a gate moves.
- `docs/WORKFLOW.md` has the session ritual and definition of done.

## Known gaps

Real embeddings, auth, amendment/effective-date logic, and multi-tenant isolation are deliberately out of scope for this slice. See README limits and `docs/ARCHITECTURE.md` for the scale path.
