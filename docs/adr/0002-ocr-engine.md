# 0002: Choose an OCR engine

Status: Accepted
Date: 2026-11-25

## Context

Scanned lease PDFs have no text layer. Today they are flagged and extraction pauses. A pilot needs scans to work, with visible confidence and an honest failure mode.

The choice affects privacy, per-page cost, accuracy, deployment complexity, and test hermeticity. Customer documents may contain names, addresses, and financial terms.

## Options

### A. Local Tesseract through ocrmypdf

- Pros: no data egress, no per-page cost, works offline, easy to test with a fake engine.
- Cons: weaker on poor scans, tables, and unusual layouts, more CPU and memory, extra system packages.

### B. Cloud OCR (Textract, Document AI, Azure Document Intelligence)

- Pros: stronger layout and table extraction, managed scaling, confidence scores.
- Cons: documents leave the deployment, per-page cost, vendor terms, network dependency, harder tests.

### C. Hybrid, local first with cloud fallback

- Pros: privacy and cost for most pages, better accuracy where local confidence is low, explicit opt-in per tenant.
- Cons: two adapters, two failure modes, a policy for when to escalate, more tests.

## Recommendation

Start with **C**, with local Tesseract as the default and cloud escalation disabled by default. Only low-confidence pages may be sent to a configured cloud engine, and the tenant must opt in. Record the engine, confidence, and page in the audit trail.

## Decision

Use **A**, local Tesseract, for the pilot slice.

- Render pages with pypdfium2 at 300 DPI and call Tesseract 5 through pytesseract.
- Persist per-page OCR text, word boxes, engine name, and confidence.
- Default the low-confidence threshold to 60 and show it in the document and source views.
- Do not send documents to a cloud OCR service.
- Keep the `OcrEngine` protocol so a cloud fallback can be added later, with tenant opt-in.

## Consequences

- Scans work offline and stay on the deployment.
- No per-page OCR cost and no data processing agreement for OCR.
- Tesseract becomes a system dependency for scanned documents. `tesseract-ocr` is installed in the Docker image and CI.
- Accuracy is lower on poor scans, unusual layouts, and handwriting. The confidence score and the review flow make that visible.
- Chunking disables font-size heading heuristics for OCR lines because OCR has no reliable font metadata. Numbered and all-caps headings still work.
