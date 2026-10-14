"""Seed known errors into in-memory copies of records and measure how many the checks catch."""
import copy
import random
import re

from . import checks


def _corrupt(q: dict, kind: str, rng: random.Random) -> bool:
    if kind == "digit":
        m = list(re.finditer(r"\d+\.\d+|\d{3,}", q.get("question_text") or ""))
        if not m:
            return False
        m = rng.choice(m)
        d = m.group(0)
        i = rng.choice([j for j, c in enumerate(d) if c.isdigit()])
        new = str((int(d[i]) + 3) % 10)
        q["question_text"] = q["question_text"][:m.start() + i] + new + q["question_text"][m.start() + i + 1:]
        return True
    if kind == "word":
        ws = [m for m in re.finditer(r"\b[a-z]{6,}\b", q.get("question_text") or "")]
        if not ws:
            return False
        m = rng.choice(ws)
        q["question_text"] = q["question_text"][:m.start()] + "qxzvbnm" + q["question_text"][m.end():]
        return True
    if kind == "marks":
        q["marks"] = (q.get("marks") or 1) + 1
        return bool(q.get("answer"))
    if kind == "truncate":
        a = q.get("answer") or {}
        t = a.get("answer_text") or ""
        if len(t) < 120:
            return False
        a["answer_text"] = t[: len(t) // 3]
        return True
    return False


def run_selftest(papers: dict, pdfs: dict, baseline: list, n_per_kind: int = 15, seed: int = 1) -> str:
    rng = random.Random(seed)
    kinds = ["digit", "word", "marks", "truncate"]
    pids = [p for p in papers if p in pdfs]
    rng.shuffle(pids)
    base_keys = {(f.paper, f.q_no, f.sub_part, f.or_alt) for f in baseline if f.bucket == "error"}
    res = {k: [0, 0] for k in kinds}
    mutated = {}
    for kind in kinds:
        made = 0
        for pid in pids:
            if made >= n_per_kind:
                break
            p = mutated.setdefault(pid, copy.deepcopy(papers[pid]))
            modes = {x["page"]: x["mode"] for x in p.get("pages", [])}
            cands = [q for q in p["questions"] if modes.get(q.get("page")) == "digital"
                     and (checks.rec_key(q)[0], checks.rec_key(q)[1], checks.rec_key(q)[2]) not in
                     {k[1:] for k in base_keys if k[0] == pid} and not q.get("_mut")]
            rng.shuffle(cands)
            for q in cands[:1]:
                if _corrupt(q, kind, rng):
                    q["_mut"] = kind
                    made += 1
    subset = {pid: p for pid, p in mutated.items() if any(q.get("_mut") for q in p["questions"])}
    found = checks.run_checks(subset, pdfs)
    hit = {}
    for f in found:
        if f.bucket == "error" and f.severity != "low":
            hit.setdefault((f.paper, f.q_no, f.sub_part, f.or_alt), set()).add(f.check)
        elif f.bucket == "error":
            hit.setdefault((f.paper, f.q_no, f.sub_part, f.or_alt), set()).add(f.check + "(low)")
    out = ["self-test: seeded corruptions in digital-page records, detected by any non-baseline finding"]
    for pid, p in subset.items():
        for q in p["questions"]:
            kind = q.get("_mut")
            if not kind:
                continue
            res[kind][1] += 1
            if checks.rec_key(q) and (pid,) + checks.rec_key(q) in hit:
                res[kind][0] += 1
    for k, (d, n) in res.items():
        out.append(f"  {k:9s} {d}/{n} detected" + ("" if n else " (no candidates)"))
    out.append("  note: 'truncate' is expected to be undetected: the checks look for words that are not in the "
               "source, not for text that is missing from the record.")
    return "\n".join(out)
