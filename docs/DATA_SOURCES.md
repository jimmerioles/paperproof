# Public real-lease corpus

A private sample of real leases was sourced from SEC EDGAR for local evaluation. The documents are not committed. The corpus lives at `data/private/real-leases/` and is covered by the `data/` gitignore rule.

## What was collected

| Property | Value |
| --- | --- |
| Documents | 20 |
| Unique companies | 20 |
| Pages | 1,068 |
| Filings | 8-K, 10-K, 10-Q |
| Filed range | August 2020 to November 2026 |
| Source format | SEC HTML exhibit, rendered to PDF locally with Chromium |
| Storage | `data/private/real-leases/`, about 11 MB |
| Manifest | `data/private/real-leases/manifest.json` |

The manifest records each company, CIK, accession, form, filing date, exhibit description, source URL, SHA-256, page count, character count, and keyword checks.

## How it was sourced

1. SEC EDGAR full-text search for lease exhibits (`"lease agreement"`, `"office lease"`, `"lease" "premises" "landlord"`).
2. Filtered to HTML or PDF leases, excluding amendments, forms of agreements, equipment leases, and press releases.
3. Selected one document from each of 20 companies, preferring recent filings.
4. Rendered HTML exhibits to PDF locally with headless Chromium.
5. Validated text with pdfplumber. Every document has at least 5,000 characters and mentions lease, premises, rent, and landlord or tenant.
6. Ingested all 20 into a temporary Paperproof database. All reached `indexed`, with 3,712 chunks total.

## Legal and privacy notes

- SEC filings are public, but they remain third-party documents. This is not a license for redistribution or commercial model training.
- The corpus is commercial real estate and equipment-adjacent leasing, not residential leasing.
- Documents may contain names, addresses, and commercial terms. Treat them as private. Do not commit, publish, or include them in a release.
- No attempt was made to remove PII from the rendered PDFs. Redact before sharing with anyone.
- Review the SEC's terms and your own counsel's guidance before using the documents beyond internal evaluation.

## Domain mismatch

The current extraction template is residential. A spot check on two documents found both useful signal and expected failures:

- A $300,000 security deposit and a sublet consent clause were found with exact citations.
- Base rent tables were not found by the residential `monthly rent of $...` rule.
- Late fees were missed.
- Notice periods were sometimes taken from a sublease or termination clause rather than the lease-end notice.
- Renewal terms were sometimes confused with lease-year definitions.

This is the correct kind of failure for a real corpus to expose. It does not mean the pipeline is broken. It means the residential template does not model commercial leases.

## What this clears and does not clear

It clears the **document sourcing** problem for a real-world stress set. It gives 20 public, text-based, long, messy contracts with page-level citations.

It does not clear the **residential pilot gate**. For that, the corpus must match the target market, and 200 fields must be labeled by a human. Options:

1. Source 20 residential leases from a design partner under a data use agreement.
2. License a residential corpus such as Kled.
3. Add a commercial lease template and label this commercial corpus if the target market is commercial.

Until then, this corpus is for retrieval and layout stress testing, not accuracy claims.
