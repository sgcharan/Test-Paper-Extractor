# cbse_verify

Read-only verification of the extracted JSON (`out/<run>/chemistry-*.json`) against the source PDFs.
It never writes to the extraction output or touches `cbse_extract`; everything goes to `<out>_verify/`.
No extra dependencies (uses PyMuPDF, already required by `cbse_extract`).

## Run

    python -m cbse_verify --out ./out/full --pdf-dir <folder with the PDFs> [<more folders>]

Options: `--sample 4` (percent of unflagged records added to the review pack), `--no-pack`,
`--selftest` (seed known errors and report how many are detected), `--llm-check` (optional second-model
judge, costs tokens, uses its own cache), `--score verdicts.json`.

## Works on both shapes
Point `--out` at either the raw extraction (`out/full`, split sub-part records) or the merged output of
`cbse_merge` (`out/full_merged`, one record per question with a `parts` list). On merged data the checks use the
pages of every part, `parts` adds checks (a part without an answer, part marks adding up, part marks vs scheme),
and the review pack shows each part's question and scheme page. The split-into-sub-parts tick box only appears
on raw (unmerged) records.

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
- `--score` gives an unbiased error-rate estimate only from the *random* part of the sample. A "wrong" verdict
  that only has the split-into-sub-parts tick (no field ticked) is counted as structural, not as a content error.
  On merged data, mark a record ok when its content is right and tick fields only for real content errors.
