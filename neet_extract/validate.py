"""Sanity checks for NEET records. Anything flagged goes to the human review pass."""
import re
from pathlib import Path

import fitz  # PyMuPDF

from cbse_extract.validate import UNICODE_SUBSUP, _balanced_ce

from .schemas import UNKNOWN_CHAPTER

# 'Answer (3)', 'Answer Key: (3)', 'Ans. [3]', 'Ans. [Bonus]', 'Solution: (2,3)'; letters a-d are 1-4 (Vedantu booklets)
PRINTED_ANSWER = re.compile(
    r"(?:Answer(?:\s*Key)?|Ans\.?|Solution)\s*[:\-]?\s*[\(\[]\s*"
    r"((?:[1-4a-dA-D](?:\s*(?:,|&|and|or)\s*)?)+|Bonus)\s*[\)\]]", re.I)


def printed_answers(pdf: Path) -> list[frozenset]:
    """Accepted options printed in the text layer, in reading order (empty set for 'Bonus'; [] for scanned PDFs)."""
    with fitz.open(pdf) as doc:
        text = "\n".join(p.get_text() for p in doc)
    out = []
    for m in PRINTED_ANSWER.finditer(text):
        bonus = m.group(1).lower() == "bonus"
        out.append(frozenset(() if bonus else (int(c) if c.isdigit() else "abcd".index(c.lower()) + 1
                                               for c in re.findall(r"[1-4a-dA-D]", m.group(1)))))
    return out


def validate_record(rec: dict) -> list[str]:
    flags = []
    text = rec.get("question_text", "") + rec.get("solution_text", "") + "".join(rec.get("options") or [])
    if UNICODE_SUBSUP.search(text):
        flags.append("unicode sub/superscripts present (should be \\ce{} or LaTeX)")
    if not _balanced_ce(text):
        flags.append("unbalanced \\ce{...}")
    if "[ILLEGIBLE]" in text:
        flags.append("illegible text")
    if rec.get("chapter") == UNKNOWN_CHAPTER:
        flags.append("chapter unknown")
    if len(rec.get("options") or []) != 4:
        flags.append(f"{len(rec.get('options') or [])} options instead of 4")
    if rec.get("correct_option") not in (1, 2, 3, 4) and not rec.get("accepted_options") and not rec.get("answer_note"):
        flags.append("no answer printed or extracted")
    if not (rec.get("solution_text") or "").strip():
        flags.append("solution has no text (the booklet prints only the answer, or it was missed)")
    if not (rec.get("question_text") or "").strip():
        flags.append("empty question")
    for f in rec.get("figures", []):
        if not f.get("crop_path"):
            flags.append("figure bbox could not be cropped")
        flags += f.get("flags", [])
    return flags


def validate_paper(records: list[dict], printed: list[frozenset]) -> list[str]:
    """Paper-level checks, plus a cross-check of correct_option against the answers in the PDF text layer."""
    flags = []
    nums = [r["q_no"] for r in records]
    for n in sorted({n for n in nums if nums.count(n) > 1}):
        flags.append(f"duplicate question number {n}")
    if nums:
        gaps = [n for n in range(min(nums), max(nums) + 1) if n not in nums]
        if gaps:
            flags.append("question number(s) missing from the extraction: " + ", ".join(map(str, gaps)))
    if printed:
        if len(printed) == len(records):
            for r, p in zip(sorted(records, key=lambda r: r["q_no"]), printed):
                got = frozenset(r.get("accepted_options") or ([r["correct_option"]] if r.get("correct_option") else []))
                if got != p:
                    flags.append(f"Q{r['q_no']}: extracted answer {sorted(got) or r.get('answer_note')} "
                                 f"but text layer prints {sorted(p) or 'Bonus'}")
        else:
            flags.append(f"text layer has {len(printed)} printed answers but {len(records)} questions were extracted "
                         "(answer cross-check skipped)")
    return flags
