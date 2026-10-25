# neet_extract

Extracts questions, correct options and worked solutions from NEET "Answers & Solutions" PDFs
(one subject per PDF, e.g. `NEET_2018_Chemistry_with_Answers.pdf`). Every NEET question is a 4-option MCQ with the
answer and solution printed right after it, so this is a separate pipeline from `cbse_extract` (no marks, sections,
sub-parts or separate marking scheme). It reuses `cbse_extract`'s page rendering, figure cropping and Gemini client.

```
export GEMINI_API_KEY=...
python -m neet_extract.run --pdf-dir <folder of PDFs> --out ./out/neet [--only "2018|2026"] [--workers 3] [--limit N]
```

Works on text-layer and scanned PDFs (pages are sent as images; the text layer is only a hint).
Pages go to the model in 5-page windows (1-page overlap) and records are merged by question number.

## Output (`out/neet/`)
- `<paper_id>.json` per PDF, `all.jsonl` (one question per line), `figures/*.png`, `usage.csv`, `review.md`, `cache/`.
- Record: `q_no`, `question_text`, `options` (4), `correct_option` (1-4), `solution_text`, `chapter` (NCERT Class 11+12
  chemistry list in `schemas.py`), `page`, `figures[{page,bbox,kind,where,crop_path}]`, `paper_id`, `flags`.
- Chemistry is written in mhchem LaTeX (`\ce{...}`); structures / reaction schemes are cropped as figures and
  marked `[FIGURE]` in the text.

## Checks (`review.md`)
Per record: option count, missing `correct_option`, empty solution, unicode sub/superscripts, unbalanced `\ce{}`,
unknown chapter, uncroppable figure. Per paper: duplicate/missing question numbers, and for text-layer PDFs a
cross-check of `correct_option` against the `Answer (N)` strings in the text layer (skipped when the counts differ).
Scanned PDFs (e.g. 2026) have no text layer, so spot-check them by eye.
