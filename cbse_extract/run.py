"""Usage:
    export GEMINI_API_KEY=...
    python -m cbse_extract.run --pdf-dir ./pdfs --out ./out [--structures]

Each PDF holds the questions followed by the answers / marking scheme at the end,
so every PDF is one paper (paper id = file name without extension).
"""
import argparse
import csv
import json
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .gemini_client import FatalAPIError, RecitationBlocked, extract
from .pdf_utils import build_parts, crop_figure
from .prompts import PAPER_PROMPT
from .schemas import Paper
from .validate import validate_paper, validate_record


def key(item: dict):
    return (str(item["q_no"]).strip(), (item.get("sub_part") or "").strip().lower(), item.get("or_alt", 0))


_MARKER = re.compile(r"^\s*\(?\s*([a-z]|[ivx]+|\d+)\s*\)\s*", re.I)


def split_combined_answer(ans: dict, n_parts: int):
    """Split one marking-scheme block covering (a)/(b) or (i)..(iv) into n_parts per-sub-part answers.

    Steps starting with a marker open a new group; unmarked steps continue the current one.
    Returns None unless the number of groups equals n_parts (the marker style may differ
    between question and scheme, e.g. (a)/(b) vs (i)/(ii), so assignment is by order).
    """
    groups = []
    for s in ans.get("steps") or []:
        if _MARKER.match(s.get("text") or "") or not groups:
            groups.append([])
        groups[-1].append(s)
    if len(groups) != n_parts or n_parts < 2:
        return None
    out = []
    for g in groups:
        marks = [s.get("marks") for s in g]
        total = sum(marks) if all(m is not None for m in marks) else None
        out.append({**ans, "steps": g, "marks_total": total, "style": "per_step",
                    "answer_text": "\n".join(_MARKER.sub("", s["text"], count=1) for s in g),
                    "split_from_combined": True})
    return out


def process_figures(pdf: Path, items: list[dict], fig_dir: Path, tag: str, structures: bool):
    for it in items:
        for n, fig in enumerate(it.get("figures", []), start=1):
            name = f"{tag}_q{it['q_no']}{it.get('sub_part') or ''}_{it.get('or_alt', 0)}_{n}.png"
            out = fig_dir / name
            if crop_figure(pdf, fig["page"], fig["bbox"], out):
                fig["crop_path"] = str(out)
                if structures and fig["kind"] in ("structure", "reaction"):
                    from .structures import image_to_smiles
                    fig["smiles"] = image_to_smiles(out)  # None if invalid; always verify by eye


def process_pdf(pdf: Path, out_dir: Path, cache: Path, fig_dir: Path, structures: bool):
    """Extract one PDF; returns (question rows, review items, usage)."""
    rows, review = [], []
    pid = pdf.stem
    parts, page_report = build_parts(pdf)
    paper, usage = extract(pdf, parts, PAPER_PROMPT, Paper, cache)
    questions = [q.model_dump(mode="json") for q in paper.questions]
    answers = [a.model_dump(mode="json") for a in paper.answers]
    process_figures(pdf, questions, fig_dir, pid + "_q", structures)
    process_figures(pdf, answers, fig_dir, pid + "_a", structures)

    ans_by_key = {key(a): a for a in answers}
    used = set()
    # Sub-part questions whose scheme is one combined block (sub_part None): split it by order.
    parts_by_qa = {}
    for q in questions:
        if q.get("sub_part") and key(q) not in ans_by_key:
            parts_by_qa.setdefault((str(q["q_no"]).strip(), q.get("or_alt", 0)), []).append(q)
    split_ans = {}
    for (qn, alt), qs in parts_by_qa.items():
        combined_key = (qn, "", alt)
        combined = ans_by_key.get(combined_key)
        pieces = split_combined_answer(combined, len(qs)) if combined else None
        if pieces:
            used.add(combined_key)
            for q, piece in zip(qs, pieces):
                piece["sub_part"] = q["sub_part"]
                split_ans[key(q)] = piece
    for q in questions:
        a = ans_by_key.get(key(q)) or split_ans.get(key(q))
        if a:
            used.add(key(q))
        q["answer"] = a
        q["paper_id"] = pid
        q["flags"] = validate_record(q)
        rows.append(q)
        if q["flags"]:
            review.append((pid, q["q_no"], q.get("sub_part"), q["flags"]))
    orphans = [a for k, a in ans_by_key.items() if k not in used]
    paper_flags = validate_paper(questions, orphans, paper.total_marks) if questions else ["no questions extracted"]
    for f in paper_flags:
        review.append((pid, "PAPER", None, [f]))

    (out_dir / f"{pid}.json").write_text(json.dumps(
        {"paper_id": pid, "exam_year": paper.exam_year, "paper_code": paper.paper_code,
         "total_marks": paper.total_marks, "pages": page_report, "paper_flags": paper_flags,
         "usage": usage, "questions": questions, "orphan_answers": orphans}, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows, review, usage


def _worker(job):
    """Runs in a worker process. Returns a tagged tuple instead of raising, so errors cross the process boundary."""
    pdf, out_dir, cache, fig_dir, structures = job
    t0 = time.time()
    try:
        rows, rev, usage = process_pdf(pdf, out_dir, cache, fig_dir, structures)
        return ("ok", pdf.stem, rows, rev, usage, time.time() - t0)
    except FatalAPIError as e:
        return ("fatal", pdf.stem, str(e), None, None, time.time() - t0)
    except RecitationBlocked as e:
        return ("skipped", pdf.stem, str(e), None, None, time.time() - t0)
    except Exception as e:  # noqa: BLE001  one bad PDF must not lose the rest of the batch
        return ("fail", pdf.stem, f"{type(e).__name__}: {str(e)[:200]}", None, None, time.time() - t0)


def write_usage(out_dir: Path, rows: list[dict]):
    """usage.csv: one row per PDF plus a total. Cached rows show the tokens spent when first fetched."""
    cols = ["paper_id", "model", "prompt_tokens", "output_tokens", "thinking_tokens", "total_tokens", "cached"]
    with open(out_dir / "usage.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])
        w.writerow(["TOTAL", ""] + [sum(r.get(c, 0) or 0 for r in rows) for c in cols[2:6]] + [""])
    if rows:
        t = sum(r.get("total_tokens", 0) or 0 for r in rows)
        print(f"Tokens: {t:,} across {len(rows)} PDFs (avg {t // len(rows):,}) -> {out_dir / 'usage.csv'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--structures", action="store_true", help="try DECIMER image->SMILES (optional install)")
    ap.add_argument("--workers", type=int, default=1, help="PDFs processed in parallel (separate processes)")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N PDFs (sorted by name)")
    args = ap.parse_args()

    pdfs = sorted(args.pdf_dir.glob("**/*.pdf"))
    if args.limit:
        pdfs = pdfs[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    cache = args.out / "cache"
    fig_dir = args.out / "figures"
    all_rows, review = [], []

    usage_rows = []
    done = 0
    t_start = time.time()
    results = {}
    skipped = []
    jobs = [(pdf, args.out, cache, fig_dir, args.structures) for pdf in pdfs]
    try:
        # Rerunning is free for finished PDFs: _worker hits the on-disk cache (and its usage sidecar).
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futs = {pool.submit(_worker, j): j[0].stem for j in jobs}
            for fut in as_completed(futs):
                kind, pid, a, b, usage, secs = fut.result()
                done += 1
                prefix = f"[{done}/{len(jobs)}] {pid}"
                if kind == "fatal":
                    review.append((pid, "PAPER", None, [f"extraction aborted: {a}"]))
                    print(f"{prefix}: FATAL, stopping batch: {a}")
                    for f in futs:
                        f.cancel()
                    break
                if kind == "skipped":
                    skipped.append((pid, a))
                    review.append((pid, "PAPER", None, ["skipped: Gemini RECITATION block (not retried)"]))
                    print(f"{prefix}: SKIPPED (recitation block, not retried)")
                    continue
                if kind == "fail":
                    review.append((pid, "PAPER", None, [f"extraction failed: {a}"]))
                    print(f"{prefix}: FAILED, continuing: {a}")
                    continue
                results[pid] = (a, b)
                usage_rows.append({"paper_id": pid, **usage})
                print(f"{prefix} ({secs:.0f}s) tokens: prompt {usage['prompt_tokens']:,} + "
                      f"output {usage['output_tokens']:,} + thinking {usage['thinking_tokens']:,} = "
                      f"{usage['total_tokens']:,}{' (cached)' if usage.get('cached') else ''}")
        for pid in sorted(results):
            all_rows.extend(results[pid][0])
            review.extend(results[pid][1])
        usage_rows.sort(key=lambda r: r["paper_id"])
        print(f"Elapsed {(time.time() - t_start) / 60:.1f} min for {len(results)}/{len(jobs)} PDFs "
              f"with {args.workers} worker(s)")
    finally:
        write_usage(args.out, usage_rows)
        if skipped:
            with open(args.out / "skipped.md", "w", encoding="utf-8") as f:
                f.write(f"# Skipped papers ({len(skipped)})\n\n"
                        "Gemini's recitation filter blocked these; they are not retried. "
                        "Enter them manually or try another model/pipeline.\n\n")
                for pid, why in sorted(skipped):
                    f.write(f"- {pid}: {why[:160]}\n")
            print(f"Skipped {len(skipped)} paper(s) -> {args.out / 'skipped.md'}")

    with open(args.out / "all.jsonl", "w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(args.out / "review.md", "w", encoding="utf-8") as f:
        f.write(f"# Review queue ({len(review)} items)\n\n")
        for pid, qn, sp, flags in review:
            f.write(f"- **{pid}** Q{qn}{sp or ''}: " + "; ".join(flags) + "\n")
    print(f"Done: {len(all_rows)} questions, {len(review)} flagged -> {args.out}/review.md")


if __name__ == "__main__":
    main()
