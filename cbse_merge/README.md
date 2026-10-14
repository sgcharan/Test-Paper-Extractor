# cbse_merge

Post-processing step that turns sub-part records (28a + 28b) into one record per question with a `parts` list.
Reads `out/<run>/chemistry-*.json`, writes `out/<run>_merged/` (per-paper JSON, `all.jsonl`, `merge_report.md`).
No API calls; `cbse_extract` and its output are not touched.

    python -m cbse_merge --out ./out/full

## Merged record
Same fields as before, so existing consumers keep working, plus:
- `marks`: sum of the parts; `sub_part`: null
- `question_text`: shared stem once (case passage, "Give reasons :" ...) then `(a) ...` `(b) ...`
- `answer`: combined `answer_text`, `steps` (prefixed with the part label), `marks_total` = sum
- `cognitive_level`: the highest level among the parts; `chapter`: the one carrying most marks
  (`chapters` lists all when they differ)
- `merged: true`, `merged_from: ["a", "b"]`, `parts: [...]` (each part keeps its own marks, text, answer,
  figures, chapter, cognitive level, page and flags)
- `or_alternative` inside a part when only that part has an OR (e.g. 31(iii) OR); a whole-question OR stays a
  separate record with `or_alt = 1`
- a lone label that only marked an OR alternative (`24a` / `24b` OR) is cleared and kept as `orig_sub_part`

## Checks done by the tool
Main-question marks per paper are identical before and after (reported in `merge_report.md`).
