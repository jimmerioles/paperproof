# Synthetic corpus

The synthetic corpus is a larger, labeled regression set. It is fully generated and fictional. It is useful for format coverage and pipeline regressions. It is not evidence of real-world accuracy.

## Generate

```bash
uv run paperproof corpus \
  --count 100 \
  --out data/synthetic \
  --seed 7 \
  --scan-rate 0.1
```

Output:

```text
data/synthetic/
  synthetic_0001.pdf
  ...
  cases.jsonl
  manifest.json
```

Evaluate it:

```bash
uv run paperproof eval \
  --cases data/synthetic/cases.jsonl \
  --docs data/synthetic \
  --report data/synthetic/report.csv
```

## What it covers

- Four layouts: standard, compact, letterhead, and table heavy.
- Cover pages and printed page labels that differ from PDF page numbers.
- 10% scanned, image-only PDFs on average, with local Tesseract OCR.
- 15% amendment pages that confirm the term and rent without conflicting values.
- Silent clauses for subletting, notice, renewal, and late fees, so abstention is exercised.
- Varied terms, rents, deposits, notice periods, sublet rules, renewal options, and late fees.
- Seven labeled cases per document, with value, page, quote phrase, and support.

## Default result

On a 100 document run with 9 scans and 20 amendments:

| Metric | Result |
| --- | --- |
| Documents | 100 |
| Cases | 700 |
| Answer accuracy | 100% |
| Citation support | 629 / 629 |
| Abstention accuracy | 71 / 71 |
| False confidence | 0 |

The rule baseline passes because the corpus is generated from the same clause patterns the rules understand. That is the point: it is a regression gate, not a benchmark.

## What it does not prove

- Real leases have inconsistent drafting, missing sections, tables in unexpected places, and poor scans.
- The amendments here confirm terms. They do not test conflicting versions or effective dates.
- Multi-column layouts and handwriting are not included yet.
- Support labels are synthetic ground truth, not independent human review.
- The PDFs and text are clean by construction. Real OCR failures are messier.

Do not use this corpus to claim pilot readiness. Use it to catch regressions and to test OCR, layout, abstention, and citation plumbing at volume.

## Reproducibility

The generator uses a seeded pseudo-random source. The same seed, count, and scan rate produce the same values and layouts, though PDF timestamps change the file bytes. The manifest records the seed and counts.
