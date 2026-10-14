# cbse_verify

Read-only verification of the extracted JSON (`out/<run>/chemistry-*.json`) against the source PDFs.
It never writes to the extraction output or touches `cbse_extract`; everything goes to `<out>_verify/`.
No extra dependencies (uses PyMuPDF, already required by `cbse_extract`).

## Run

    python -m cbse_verify --out ./out/full --pdf-dir <folder with the PDFs> [<more folders>]

Options: `--sample 4` (percent of unflagged records added to the review pack), `--no-pack`,
`--selftest` (seed known errors and report how many are detected), `--llm-check` (optional second-model
judge, costs tokens, uses its own cache), `--score verdicts.json`.

## Outputs (`out/full_verify/`)
- `verify_report.md` - counts by check and severity, worst papers, source anomalies
- `verify_findings.csv` - one row per finding (paper, question, field, check, severity, bucket, detail)
- `review_pack/index.html` - open in a browser; page crop beside the extracted record; mark ok / wrong
- `pack_manifest.json` - which records are `flagged` and which are the `random` sample (used by `--score`)

## Checks (all free)
| check | what it catches | notes |
|---|---|---|
| validator | marks vs scheme, step sums, orphans (reuses `cbse_extract.validate`) | "attempt any N" handled |
| anchor | prose words in a record that appear nowhere in the source text | pages with embedded images downgrade to low |
| words | a few unknown words (typo/hallucination) in a question or option | |
| numbers | decimals / 3+ digit numbers not on the record's page | |
| coverage | question numbers present as headings but missing from the records | |
| consensus | the same question in sibling sets (Delhi 1/2/3 ...) with different marks, options or answer | medium/high only when the question text is identical |

Findings in bucket `source_anomaly` are not extraction errors: the scheme itself says a part was deleted,
merged or has a printing error.

## Limits
- Text-layer checks cannot verify image-only (scanned) pages or equations stored as images; those records
  appear only through consensus, the optional judge, and the review-pack sample.
- A truncated answer (text missing, nothing wrong in what remains) is only partly detectable.
- `--score` gives an unbiased error-rate estimate only from the *random* part of the sample.
