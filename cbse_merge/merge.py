"""Merge sub-part records (28a + 28b) of one question into a single record with a `parts` list.

Pure post-processing: input is the extraction output folder, output is a new folder. No API calls, no
changes to cbse_extract or its output.
"""
import copy
import os
import re
from collections import Counter, defaultdict

from cbse_extract.validate import validate_paper, validate_record

COGNITIVE_ORDER = {"Remembering/Understanding": 0, "Applying": 1, "Analysing/Evaluating/Creating": 2}


def _strip_label(text: str, label: str) -> str:
    """Drop a leading '(a)' / 'a)' / '(ii)' that repeats the part's own label."""
    if not label:
        return text.strip()
    return re.sub(r"^\s*\(?\s*%s\s*[).]\s*" % re.escape(label), "", text or "", count=1, flags=re.I).strip()


def shared_stem(texts: list[str]) -> str:
    """Longest common opening that ends on a sentence/line boundary (case passage, 'Give reasons :' ...)."""
    if len(texts) < 2:
        return ""
    p = os.path.commonprefix(texts)
    cut = max(p.rfind(c) for c in (":", "\n", ".", "?"))
    if cut < 19:
        return ""
    stem = p[: cut + 1].strip()
    # the stem must leave something for every part
    return stem if all(len(t.strip()) > len(stem) + 2 for t in texts) else ""


def _union_figures(recs: list[dict], getter) -> list[dict]:
    seen, out = set(), []
    for r in recs:
        for f in getter(r) or []:
            key = (f.get("page"), tuple(f.get("bbox") or ()), f.get("crop_path"))
            if key not in seen:
                seen.add(key)
                out.append(f)
    return out


def _part(r: dict) -> dict:
    return {
        "sub_part": r.get("sub_part"),
        "marks": r.get("marks"),
        "question_text": r.get("question_text"),
        "answer": copy.deepcopy(r.get("answer")),
        "figures": copy.deepcopy(r.get("figures") or []),
        "chapter": r.get("chapter"),
        "cognitive_level": r.get("cognitive_level"),
        "page": r.get("page"),
        "flags": list(r.get("flags") or []),
    }


def merge_group(recs: list[dict]) -> dict:
    """recs: >=2 records of one question (same q_no and or_alt), each with a sub_part."""
    recs = sorted(recs, key=lambda r: (r.get("page") or 0))
    first = recs[0]
    labels = [r["sub_part"] for r in recs]
    texts = [r.get("question_text") or "" for r in recs]
    stem = shared_stem(texts)
    pieces = []
    for r, t in zip(recs, texts):
        body = t[len(stem):].strip() if stem else t.strip()
        pieces.append(f"({r['sub_part']}) {_strip_label(body, r['sub_part'])}")
    question_text = (stem + "\n" if stem else "") + "\n".join(pieces)

    answers = [r.get("answer") for r in recs]
    has_ans = [a for a in answers if a]
    answer = None
    if has_ans:
        steps = []
        for r in recs:
            a = r.get("answer") or {}
            if a.get("steps"):
                for s in a["steps"]:
                    steps.append({"text": f"({r['sub_part']}) {s['text']}", "marks": s.get("marks")})
            elif a:  # whole-answer marks: keep one step so the steps still add up to the part's marks
                steps.append({"text": f"({r['sub_part']}) {_strip_label(a.get('answer_text') or '', r['sub_part'])}",
                              "marks": a.get("marks_total")})
        totals = [a.get("marks_total") for a in has_ans]
        answer = {
            "q_no": first["q_no"], "sub_part": None, "or_alt": first.get("or_alt", 0),
            "marks_total": sum(totals) if all(t is not None for t in totals) else None,
            "style": "per_step" if any(a.get("style") == "per_step" for a in has_ans) else "whole",
            "answer_text": "\n".join(f"({r['sub_part']}) {_strip_label((r.get('answer') or {}).get('answer_text') or '', r['sub_part'])}"
                                     for r in recs if r.get("answer")),
            "steps": steps,
            "page": has_ans[0].get("page"),
            "figures": _union_figures(recs, lambda r: (r.get("answer") or {}).get("figures")),
        }

    by_marks = Counter()
    for r in recs:
        by_marks[r.get("chapter")] += r.get("marks") or 0
    chapter = by_marks.most_common(1)[0][0]
    chapters = list(dict.fromkeys(r.get("chapter") for r in recs))
    cog = max((r.get("cognitive_level") for r in recs), key=lambda c: COGNITIVE_ORDER.get(c, -1))

    merged = {k: copy.deepcopy(v) for k, v in first.items() if k not in ("answer", "flags")}
    merged.update({
        "sub_part": None,
        "marks": sum(r.get("marks") or 0 for r in recs),
        "question_text": question_text,
        "options": None,
        "is_case_based": any(r.get("is_case_based") for r in recs),
        "chapter": chapter,
        "cognitive_level": cog,
        "figures": _union_figures(recs, lambda r: r.get("figures")),
        "answer": answer,
        "merged": True,
        "merged_from": labels,
        "shared_stem": bool(stem),
        "parts": [_part(r) for r in recs],
    })
    if len(chapters) > 1:
        merged["chapters"] = chapters
    merged["flags"] = validate_record(merged)
    part_flags = [f"({r['sub_part']}) {fl}" for r in recs for fl in (r.get("flags") or [])]
    if part_flags:
        merged["part_flags"] = part_flags
    return merged


def merge_paper(paper: dict) -> tuple[dict, dict]:
    """Return (merged paper dict, stats)."""
    stats = Counter()
    groups = defaultdict(list)
    order = []
    for q in paper["questions"]:
        k = (str(q["q_no"]), int(q.get("or_alt") or 0))
        if k not in groups:
            order.append(k)
        groups[k].append(q)

    attached = set()          # OR groups folded into one part of the main question
    part_or = {}              # q_no -> (target part label, alternative record or merged record)
    for (qn, alt), recs in groups.items():
        if alt != 1 or (qn, 0) not in groups:
            continue
        main = groups[(qn, 0)]
        if len(main) < 2 or not all(r.get("sub_part") for r in main):
            continue
        main_total = sum(r.get("marks") or 0 for r in main)
        alt_total = sum(r.get("marks") or 0 for r in recs)
        if alt_total >= main_total - 0.01:
            continue                      # the alternative replaces the whole question
        labels = [r["sub_part"] for r in main]
        target = None
        if len(recs) == 1 and recs[0].get("sub_part") in labels:
            target = recs[0]["sub_part"]  # e.g. '31 iii' OR: the label says which part it replaces
        else:                             # the alternative has its own labels: match by marks, latest part first
            cands = [r["sub_part"] for r in main if abs((r.get("marks") or 0) - alt_total) < 0.01]
            target = cands[-1] if cands else None
        if target is None:
            stats["or_unattached"] += len(recs)
            continue
        attached.add((qn, alt))
        alt_rec = recs[0] if len(recs) == 1 else merge_group(recs)
        part_or[qn] = (target, alt_rec)

    out = []
    for k in order:
        if k in attached:
            stats["or_attached_to_part"] += len(groups[k])
            continue
        recs = groups[k]
        subs = [r for r in recs if r.get("sub_part")]
        if len(recs) >= 2 and len(subs) == len(recs):
            m = merge_group(recs)
            if k[1] == 0 and k[0] in part_or:
                target, alt = part_or[k[0]]
                for part in m["parts"]:
                    if part["sub_part"] == target:
                        part["or_alternative"] = _part(alt)
                        if alt.get("merged_from"):
                            part["or_alternative"]["sub_part"] = "/".join(alt["merged_from"])
                m["has_part_or_alternative"] = True
            out.append(m)
            stats["merged_questions"] += 1
            stats["merged_records_in"] += len(recs)
        elif len(recs) == 1 and recs[0].get("sub_part"):
            r = copy.deepcopy(recs[0])      # a label on an OR alternative, not a real split
            r["orig_sub_part"] = r["sub_part"]
            r["sub_part"] = None
            if r.get("answer"):
                r["answer"]["sub_part"] = None
            r["merged"] = False
            out.append(r)
            stats["lone_label_cleared"] += 1
        else:
            for r in recs:
                r = copy.deepcopy(r)
                r["merged"] = False
                out.append(r)
            stats["unchanged"] += len(recs)

    merged = {k: v for k, v in paper.items() if k != "questions"}
    merged["questions"] = out
    merged["paper_flags"] = validate_paper(out, paper.get("orphan_answers", []), paper.get("total_marks"))
    merged["merge"] = {"records_before": len(paper["questions"]), "records_after": len(out), **dict(stats)}
    return merged, stats


def main_marks(paper: dict) -> float:
    return round(sum(q["marks"] for q in paper["questions"] if int(q.get("or_alt") or 0) == 0), 2)
