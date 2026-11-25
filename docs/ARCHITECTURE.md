# Architecture

## Goal

Turn a lease PDF into a small set of structured terms where every value is tied to a verbatim quote that a reviewer can check on the page.

The product bet is simple: accuracy claims are cheap, checkable evidence is expensive. The system is designed around producing and protecting that evidence.

## Non-goals

- General chat over documents.
- Legal advice or clause interpretation.
- Cloud OCR or handwriting recognition.
- Multi-tenant SaaS operations.
- Real-time collaboration.

## System map

```text
                +---------------------+
  PDF upload -> | ingest/pipeline.py  |
                +----------+----------+
                           |
              +------------+-------------+
              |                          |
       pages + words               section chunks
       (pdfplumber)                (headings, overlap)
              |                          |
              |                  +-------+--------+
              |                  |                |
              |               FTS5 index     hash embeddings
              |                  |                |
              +------------------+----------------+
                                 |
                          hybrid retrieval
                        (BM25 + cosine + RRF)
                                 |
                     +-----------+-----------+
                     |                       |
              RuleExtractor            LLMExtractor
                     |                       |
                     +-----------+-----------+
                                 |
                          verify_quote()
                    (exact -> fuzzy -> boxes)
                                 |
                    extractions + audit_log
                                 |
                     FastAPI + Jinja review desk
```

## Trust boundary

`paperproof/extract/verify.py` is the only place allowed to turn model output into a citation.

### Normalization

Before matching, the verifier:

- applies Unicode NFKC,
- normalizes curly quotes, en/em dashes, non-breaking spaces, and soft hyphens,
- collapses whitespace,
- builds a token stream from every word on the page,
- strips edge punctuation from each token while preserving internal punctuation and currency symbols.

Page tokens are joined with single spaces, and each token remembers its source `Word` box. This gives a bidirectional map between normalized text offsets and PDF coordinates.

### Exact match

The quote is tokenized with the same rules, joined, and searched in the page token stream. If found, every overlapping word is selected, the canonical quote is rebuilt from the original words, and the words are grouped into line boxes.

### Fuzzy match

Fuzzy matching exists for OCR noise, ligatures, and hyphenated line breaks. It uses `difflib.SequenceMatcher` over page and quote tokens, then merges nearby matching blocks when the gaps are at most two tokens on each side. A cluster is accepted when:

- it contains at least three matched tokens,
- quote coverage is at least 80 percent,
- the page span is not more than three tokens longer than the quote.

The result is marked `fuzzy`, confidence is multiplied by 0.85, and the UI labels it. Fuzzy matches are never silent.

### Page resolution

The extractor supplies a page hint from the retrieved chunk. The verifier searches the hint page first for an exact match, then the remaining pages, then repeats the search with fuzzy matching. This catches page hints that are off because a chunk spans pages.

### Highlight boxes

Word boxes are in PDF points. Words on the same line (vertical overlap within 3 points) are unioned into a line box. `presenters.boxes_percent` converts points to percentages of the page width and height. The frontend positions absolutely positioned spans over the page PNG.

This is why the renderer and parser must agree on page dimensions. `pages.width` and `pages.height` are stored at ingest time.

### Printed page labels

The parser looks at the first and last two non-empty lines of each page for patterns like `Page 3 of 12` or a bare page number. The detected number is stored as `printed_label`. The UI shows `p. 3` for citations but keeps the PDF page for coordinates and navigation. When they differ, the caption shows both.

## Data model

SQLite, WAL mode, foreign keys on.

| Table | Purpose |
| --- | --- |
| `documents` | One row per unique PDF, keyed by SHA-256. Status is `indexed`, `needs_ocr`, or `failed`. OCR page count and confidence are stored alongside. |
| `pages` | Page text, dimensions, printed label, compact word boxes as JSON, and OCR flag, engine, and confidence. |
| `chunks` | Section-aware passages with heading, ordinal, and page range. |
| `chunks_fts` | FTS5 external-content index over chunk text and headings, porter stemming. |
| `embeddings` | Float32 vectors as blobs, one per chunk. |
| `extractions` | One row per document, template, and field. Unique constraint makes reruns idempotent. |
| `audit_log` | Append-only event log with actor, action, entity, and JSON detail. |

Extraction statuses form a small state machine:

```text
pending -> approved
pending -> rejected
abstained (terminal until rerun)
failed (terminal until rerun)
```

Rerunning extraction clears review state for that field. This is deliberate: a new model or prompt invalidates the old approval.

## Ingestion

`ingest_file` hashes the source, checks for duplicates, copies it to `data/uploads/<doc_id>.pdf`, parses it, and writes pages, chunks, and embeddings in one transaction. On any exception the copied file is removed.

Chunking:

- skip table-of-contents pages detected by dot leaders,
- skip page furniture such as `Page 2 of 4`,
- detect headings by font size, numbering, or all-caps formatting,
- split sections at roughly 900 characters with 160 characters of overlap,
- join hyphenated line breaks,
- keep page ranges for retrieval hints.

Scanned documents are detected when the average alphanumeric characters per page falls below 40. Pages below the per-page text threshold are rendered at 300 DPI and passed to Tesseract. The OCR output replaces the empty page text and provides word boxes for highlights, plus a page confidence score. A document whose OCR still leaves too little text is stored for viewing but not chunked, and extraction returns an explicit OCR-required abstention for every field.

OCR lines are marked as OCR in the chunker, so font-size heading heuristics are disabled for them. Numbering and all-caps headings still work. Low-confidence pages are surfaced in the document banner and the source view.

## Retrieval

Two independent rankings:

1. **BM25** through FTS5. Query tokens are sanitized to alphanumerics, prefixed with `*`, and OR-joined. This handles names, section numbers, and dollar amounts.
2. **Cosine similarity** over hashed embeddings. The default embedder uses word unigrams, bigrams, and character 4-grams with stable CRC32 hashing, then L2 normalizes. It is deterministic and needs no model download.

The lists are fused with reciprocal rank fusion (`1 / (60 + rank)`). The fused set is reranked with lexical coverage of the query terms and a heading bonus. The final score is 65 percent normalized RRF, 30 percent coverage, 5 percent heading match.

This is intentionally simple and inspectable. The `Embedder` protocol is the seam for a neural model. No other code needs to change.

## Extraction

`Template` defines fields with a name, label, type, question, hints, allowed enum values, and unit. The lease template has seven fields.

`RuleExtractor` is a per-field parser over retrieved sentences. It is fast, offline, and deterministic. It is also brittle, and the README says so.

`LLMExtractor` calls an OpenAI-compatible `/chat/completions` endpoint with:

- a strict system prompt: use only passages, quote verbatim, abstain if absent,
- typed instructions per field,
- at most six passages, each capped at 1,800 characters,
- JSON object response format with a fallback for servers that reject it.

The model returns `{value, quote, confidence, abstained, reason}`. Values are coerced to the field type. An invalid enum or number becomes an abstention with a reason, not a bad record.

`extract_document` orchestrates:

1. If the document still needs OCR after the OCR pass, abstain for every field.
2. Retrieve field-specific passages, scoped to the document.
3. Extract a candidate.
4. Verify the quote.
5. On verification failure with the LLM, retry once with verifier feedback.
6. Persist pending, abstained, or failed with an audit summary.
7. If the LLM is unreachable, fall back to rules for the rest of the document and record the fallback reason.

## Review desk

Server-rendered FastAPI and Jinja. No client-side framework and no build step.

The document page is a two-pane desk. The left pane is an ordered list of fields with values, quotes, statuses, and review actions. The right pane is a sticky source viewer with the quote above the page image and highlight boxes over the clause. Page images are rendered on demand with `pypdfium2` at 2x and cached under `data/renders`.

Review posts are ordinary form submissions. The route writes the decision, adds an audit event, computes the next pending field in template order, and redirects to it. The page works without JavaScript; JS only improves record switching, paging, drag and drop, and flash dismissal.

## Evaluation

`evals/cases.jsonl` contains 29 cases across the sample corpus:

- 25 answerable fields,
- 3 deliberate abstentions in a silent lease,
- 1 scanned document that must abstain.

For each answerable case the runner checks:

- value equality or substring,
- quote presence,
- independent re-verification of the persisted quote,
- that the verification page equals the stored page,
- whether the match was exact or fuzzy.

It also counts false confidence: a wrong answer with confidence at or above 0.7. The eval fails if any case is wrong or if any answer lacks an independently verified citation.

The eval runs on every CI push. Prompt, parser, and retrieval changes are not done until it passes.

## Backups

`paperproof backup` uses SQLite's online backup API for a consistent snapshot, then copies uploads and rendered pages and writes a manifest with schema version and row counts. `paperproof restore` refuses a non-empty target, verifies the snapshot with `PRAGMA integrity_check`, and copies the files into a fresh data directory.

The session secret is deliberately not included. Users and password hashes come back with the database, but existing browser sessions are invalidated and the admin signs in again. `paperproof restore-drill` creates a throwaway library, backs it up, restores it, and compares row counts. The drill runs in CI.

Backups contain customer documents and are not encrypted by the application. Encrypt the backup volume or destination, restrict access, and add off-site storage before a pilot.

## Security and privacy

Assumptions: local or trusted network, single team, no hostile multi-tenant users.

### Authentication and sessions

A single admin account is stored in the `users` table with an Argon2id hash. Login creates a signed session cookie with a per-session CSRF token. The auth middleware loads the session, checks the user against the database, and redirects anonymous visitors to `/login`. Every state-changing form carries a hidden CSRF token and every POST route depends on `csrf_protect`.

Session cookies are HttpOnly, SameSite=Lax, and Secure when `PAPERPROOF_ENV=prod`. The signing secret comes from `PAPERPROOF_SESSION_SECRET` or a 0600 file under the data directory. Failed logins lock out per IP and username for a configurable window. The limiter is in memory, which is enough for one process and a pilot.

`PAPERPROOF_AUTH_DISABLED=1` exists for local development and is rejected outside `PAPERPROOF_ENV=dev`.

### Other controls

- Uploads are size limited and stored under generated IDs. Original filenames are never used as paths.
- All SQL is parameterized. FTS input is tokenized.
- Jinja autoescaping is on. The only `safe` filter is for search snippets that are escaped before `<mark>` insertion.
- CSP forbids inline scripts and external origins. Fonts are vendored.
- The server binds to `127.0.0.1` by default. Authentication is enabled by default; set `PAPERPROOF_ENV=prod` and terminate TLS before exposing it.
- OCR runs locally with Tesseract. Scanned pages are not sent to an external service.
- LLM mode sends only retrieved passages to the configured endpoint. If documents are sensitive, use a local model or a provider with the right data terms.
- Retrieved text is untrusted input for the LLM. The prompt says to ignore instructions inside passages, but prompt injection is still possible. The verifier limits the damage to incorrect extraction, and a human must approve before a record is final. The LLM has no tools and no write access.

Production hardening would add: auth, per-tenant row filters, parser isolation and timeouts, antivirus scanning, outbound allowlists, and encrypted storage.

## Scaling path

| Bottleneck | Current | Next |
| --- | --- | --- |
| Documents | SQLite | Postgres |
| Vectors | Brute force in NumPy | pgvector with HNSW |
| Files | Local disk | S3-compatible object storage |
| Rendering | On demand | Background worker with cache |
| Ingestion | Synchronous | Durable queue with retries |
| Search | Single process | Dedicated index or OpenSearch |
| Auth | None | OIDC, orgs, roles, row-level security |
| Evals | CLI | CI gate plus labeled production corrections |

The schema and service boundaries are designed so these swaps do not touch the verifier or the review UI contract.

## Decisions and tradeoffs

**SQLite over Postgres.** One file, no service, trivial demos and tests. The cost is concurrency and vector search performance. The schema is portable.

**Server-rendered over React.** The core interaction is reading a page and clicking approve. A build step would slow the first version. The cost is a smaller ecosystem for complex interactions.

**Hashed embeddings over a downloaded model.** Deterministic tests and zero network. The cost is semantic recall. The protocol makes the upgrade a one-class change.

**Rule baseline plus LLM.** The baseline proves the loop and keeps CI hermetic. The LLM is the quality path. The cost is two extraction paths to maintain, mitigated by a shared `Candidate` contract.

**Verify before persist.** The verifier can reject a correct answer if the quote is paraphrased. That is the right failure: a rejected citation is visible, a fake one is not.

**Abstain over infer.** A blank field is annoying. A wrong field with a plausible citation is dangerous. The product chooses the visible failure.

**FSL over MIT.** The source stays public and usable, including for internal commercial work, but a competitor cannot offer it as a competing hosted service for two years. Each version converts to Apache 2.0 after that. The cost is that FSL is source-available, not OSI open source, so the README says so plainly.
