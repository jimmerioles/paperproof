# Evals

Paperproof has two evaluation sets:

1. **Synthetic golden set** in `evals/cases.jsonl`. It runs in CI, is fast, and protects the extraction and citation contract.
2. **Private real-document set**. It is not committed. It measures whether extraction works on real leases, scans, tables, and unusual drafting.

The synthetic set proves the loop. The private set decides whether the product is pilot-ready.

## Case format

One JSON object per line:

```json
{"doc": "lease_02_beacon_street.pdf", "field": "term_months", "value": 12, "support": true, "page": 3}
{"doc": "lease_04_marlowe_terrace.pdf", "field": "notice_days", "abstain": true}
{"doc": "lease_01_alder_court.pdf", "field": "renewal_option", "contains": "twelve (12) months", "support": true}
```

| Key | Required | Meaning |
| --- | --- | --- |
| `doc` | yes | PDF filename or SHA-256 of the source file. |
| `field` | yes | Template field, for example `term_months`. |
| `value` | one of value, contains, or abstain | Expected exact value. Numbers compare with a 0.01 tolerance. |
| `contains` | one of value, contains, or abstain | Expected substring for text fields. |
| `abstain` | one of value, contains, or abstain | The document is silent and the system must not answer. |
| `support` | no | Human label: does the verified quote actually prove the value? |
| `page` | no | Expected PDF page. The citation must land here when set. |
| `quote_contains` | no | Expected phrase in the verified quote, for high-risk fields. |

`support` is the important label. A quote can exist on the page but still fail to prove the value. Mark `support: true` only when a reviewer would accept the quote as evidence.

## Run

Synthetic set:

```bash
uv run paperproof eval
```

Private set:

```bash
uv run paperproof eval \
  --cases /secure/paperproof/real-cases.jsonl \
  --docs /secure/paperproof/leases \
  --report /secure/paperproof/report.csv \
  --verbose
```

- `--docs` ingests every PDF under the directory. Cases match by filename or SHA-256.
- `--report` writes one CSV row per case with expected, extracted, citation, support, page, correctness, and false confidence.
- `--llm` uses the configured LLM extractor. Without it, the rule baseline runs.
- `--keep` keeps the temporary eval database for inspection.

Do not commit customer documents, cases, or reports. Keep them outside the repo or under a private path.

A private sample of 20 real SEC lease exhibits is documented in [DATA_SOURCES.md](DATA_SOURCES.md). It is commercial leasing, not residential, and it is stored outside git.

## Metrics

| Metric | Gate |
| --- | --- |
| Answer accuracy | 90% or higher |
| Answer precision | 90% or higher |
| Answer recall | 90% or higher |
| Citation existence | 100%, enforced by the verifier |
| Citation support on labeled cases | 98% or higher |
| Unverified citations shown | 0 |
| False confidence | 0 |
| Abstention accuracy | 100% on silent documents |

The per-field table shows where the failures cluster. A field at 60% is a product problem even if the aggregate is 90%.

## Labeling workflow

1. Get permission for at least 20 real documents and remove or redact data you do not need.
2. Run the app against a private data directory and extract one document.
3. For each field, read the cited page and write the expected value yourself. Do not copy the model output.
4. Mark `support: true` only if the quote proves the value. Mark `support: false` if the quote exists but does not prove it.
5. Add a page for high-risk fields and a `quote_contains` phrase when the clause wording matters.
6. Start with 10 fields per document, then stop when you have 200 labeled fields.
7. Run the eval, inspect the per-field table, and keep the report with the release notes.

If retrieval misses paraphrased clauses, the eval will show low recall before any model change. That is the signal to add neural embeddings, not a hunch.

## Synthetic corpus

For volume, generate a larger labeled corpus:

```bash
uv run paperproof corpus --count 100 --out data/synthetic --seed 7 --scan-rate 0.1
uv run paperproof eval --cases data/synthetic/cases.jsonl --docs data/synthetic --report data/synthetic/report.csv
```

It covers four layouts, scans, tables, amendments, silent clauses, and 700 labeled cases at the default size. It is a regression gate. It is not real-world evidence. See [SYNTHETIC_CORPUS.md](SYNTHETIC_CORPUS.md).

## Current synthetic result

The 35 case set is 35/35 correct with 32/32 exact citations. It includes a silent lease and a scanned lease recovered by OCR. It does not have human support labels, so support is reported as not labeled.
