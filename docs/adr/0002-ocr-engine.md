# 0002: Choose an OCR engine

Status: Proposed
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

TBD. Write the chosen option here before starting the OCR implementation.

## Consequences

TBD after the decision. Include the deployment packages, cost model, data flow, and test strategy.
