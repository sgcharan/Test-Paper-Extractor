"""Sanity checks. Anything flagged goes to the human review pass."""
import re

UNICODE_SUBSUP = re.compile("[\u2080-\u2089\u2070\u00b9\u00b2\u00b3\u2074-\u2079\u207a\u207b\u208a\u208b]")
EXPECTED_TOTAL = 70  # CBSE Class 12 Chemistry theory paper
# "Attempt any five of the following" / "(Any three)": the scheme lists every part, so step marks exceed the question marks.
CHOICE_RE = re.compile(r"\bany\s+(one|two|three|four|five|six|seven|\d+)\b", re.I)


def _balanced_ce(text: str) -> bool:
    depth = 0
    for m in re.finditer(r"\\ce\{", text):
        i, depth = m.end(), 1
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        if depth:
            return False
    return True


def validate_record(rec: dict) -> list[str]:
    flags = []
    qt = rec.get("question_text", "")
    ans = rec.get("answer") or {}
    at = ans.get("answer_text", "")

    if UNICODE_SUBSUP.search(qt + at):
        flags.append("unicode sub/superscripts present (should be \\ce{} or LaTeX)")
    if not _balanced_ce(qt + at):
        flags.append("unbalanced \\ce{...}")
    if "[ILLEGIBLE]" in qt + at:
        flags.append("illegible text")
    if rec.get("chapter") == "Other / Unknown":
        flags.append("chapter unknown")
    if not ans:
        flags.append("no matching answer in marking scheme")
    else:
        steps = ans.get("steps") or []
        is_choice = bool(CHOICE_RE.search(qt) or CHOICE_RE.search(at))
        if steps and not is_choice and all(s.get("marks") is not None for s in steps):
            total = sum(s["marks"] for s in steps)
            if abs(total - (rec.get("marks") or 0)) > 0.01:
                flags.append(f"step marks sum {total} != question marks {rec.get('marks')}")
        mt = ans.get("marks_total")
        if mt is not None and abs(mt - (rec.get("marks") or 0)) > 0.01:
            flags.append(f"scheme marks {mt} != question marks {rec.get('marks')}")
    for f in rec.get("figures", []) + ans.get("figures", []):
        if not f.get("crop_path"):
            flags.append("figure bbox could not be cropped")
    if rec.get("options") is not None and len(rec["options"]) not in (4,):
        flags.append(f"MCQ has {len(rec['options'])} options")
    return flags


def validate_paper(records: list[dict], orphan_answers: list[dict], declared_total: float | None = None) -> list[str]:
    flags = []
    # Term papers are 35 marks; trust the printed total when it is plausible, else assume the 70-mark paper.
    expected = declared_total if declared_total and 20 <= declared_total <= 100 else EXPECTED_TOTAL
    main = [r for r in records if r.get("or_alt", 0) == 0]
    main_total = sum(r["marks"] for r in main)
    # Marks that are not multiples of 0.5 (e.g. 0.77 per MCQ in the 2021 Term 1 papers) mean the paper
    # scales "attempt any N" marks, so the printed sum legitimately exceeds the total.
    scaled = any((r["marks"] * 2) % 1 > 0.01 for r in main)
    if not scaled and abs(main_total - expected) > 0.01:
        msg = f"sum of marks for main questions = {main_total}, expected {expected:g}"
        nums = sorted({int(str(r["q_no"])) for r in records if str(r["q_no"]).isdigit()})
        gaps = [n for n in range(nums[0], nums[-1] + 1) if n not in nums] if nums else []
        if gaps:
            msg += f" (question number(s) missing from the extraction: {', '.join(map(str, gaps))})"
        flags.append(msg)
    if orphan_answers:
        flags.append(f"{len(orphan_answers)} marking-scheme entries matched no question: "
                     + ", ".join(f"{a['q_no']}{a.get('sub_part') or ''}/{a.get('or_alt', 0)}" for a in orphan_answers))
    seen = set()
    for r in records:
        k = (r["q_no"], r.get("sub_part"), r.get("or_alt", 0))
        if k in seen:
            flags.append(f"duplicate question key {k}")
        seen.add(k)
    return flags
