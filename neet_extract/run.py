"""Usage:
    export GEMINI_API_KEY=...
    python -m neet_extract.run --pdf-dir <dir with NEET_<year>_Chemistry_with_Answers.pdf> --out ./out/neet

Each PDF is one subject's 'Answers & Solutions' booklet. Pages are sent in overlapping windows (one model call
each) so long solutions fit the output limit; records are merged by question number.
"""
import argparse
import json
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import fitz  # PyMuPDF

from cbse_extract.gemini_client import FatalAPIError, RecitationBlocked, extract
from cbse_extract.pdf_utils import build_parts, crop_figure
from cbse_extract.run import write_usage

from .figures import refine
from .prompts import chunk_prompt
from .schemas import NeetChunk
from .validate import printed_answers, validate_paper, validate_record

CHUNK_PAGES = 5  # pages per model call; consecutive windows share one page so a split question is seen whole


def group_pages(parts: list) -> list[list]:
    """build_parts gives a flat list: '=== PAGE n ===', image, optional text hint, ... Regroup per page."""
    pages = []
    for p in parts:
        if isinstance(p, str) and p.startswith("=== PAGE "):
            pages.append([])
        pages[-1].append(p)
    return pages


def windows(n_pages: int, size: int = CHUNK_PAGES):
    """[(first, last)] 1-indexed, inclusive, overlapping by one page."""
    out, first = [], 1
    while True:
        last = min(first + size - 1, n_pages)
        out.append((first, last))
        if last >= n_pages:
            return out
        first = last


SOL_PREFIX = re.compile(r"^\s*(?:Sol(?:ution)?\s*[.:]\s*)+", re.I)


SUPER = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋", "0123456789+-")
SUP_RUN = re.compile("[⁰¹²³⁴-⁻]+")
SUB_RUN = re.compile("[₀-₋]+")


def latexify(t: str) -> str:
    """Unicode super/subscript runs -> LaTeX (the model occasionally copies them from the PDF)."""
    t = SUP_RUN.sub(lambda m: "$^{" + m.group().translate(SUPER) + "}$", t)
    return SUB_RUN.sub(lambda m: "$_{" + m.group().translate(SUB) + "}$", t)


def _norm(o: str) -> str:
    return re.sub(r"[\s$]", "", o)


def clean(d: dict) -> dict:
    """Drop the printed 'Sol.' label, bullet glyphs and a spurious 5th option; convert unicode sub/superscripts."""
    sol = re.sub("[�•]\s*", "- ", d.get("solution_text", ""))
    d["solution_text"] = latexify(SOL_PREFIX.sub("", sol).strip())
    d["question_text"] = latexify(d.get("question_text", ""))
    opts = [latexify(o) for o in d.get("options", [])]
    while len(opts) > 4 and (not opts[-1].strip() or _norm(opts[-1]) in {_norm(o) for o in opts[:-1]}):
        opts.pop()
    d["options"] = opts
    return d


def completeness(q: dict):
    has_key = q.get("correct_option") is not None or bool(q.get("answer_note"))
    return (has_key, len(q.get("solution_text", "")), len(q.get("options", [])))


def merge(chunks: list[NeetChunk], subject: str) -> list[dict]:
    """One record per q_no; a question seen in two windows keeps its most complete version.
    Questions of another subject (shared boundary pages) are dropped."""
    best = {}
    for ch in chunks:
        for q in ch.questions:
            d = clean(q.model_dump(mode="json"))
            if d["subject"].strip().lower() != subject:
                continue
            if d["q_no"] not in best or completeness(d) > completeness(best[d["q_no"]]):
                best[d["q_no"]] = d
    return [best[k] for k in sorted(best)]


def process_figures(pdf: Path, records: list[dict], fig_dir: Path, tag: str):
    with fitz.open(pdf) as doc:
        for r in records:
            for n, fig in enumerate(r.get("figures", []), start=1):
                ref = refine(doc, fig)
                fig["crop_bbox"], fig["crop_method"], fig["flags"] = ref["crop_bbox"], ref["crop_method"], ref["flags"]
                out = fig_dir / f"{tag}_q{r['q_no']}_{fig.get('where', 'q')}_{n}.png"
                if crop_figure(pdf, fig["page"], fig["crop_bbox"], out, pad=0.0):
                    fig["crop_path"] = str(out)


def process_pdf(pdf: Path, out_dir: Path, cache: Path, fig_dir: Path, subject: str):
    pid = pdf.stem
    pages = group_pages(build_parts(pdf)[0])
    chunks, usages = [], []
    for first, last in windows(len(pages)):
        parts = [p for page in pages[first - 1:last] for p in page]
        ch, usage = extract(pdf, parts, chunk_prompt(subject, first, last), NeetChunk, cache)
        chunks.append(ch)
        usages.append(usage)
    records = merge(chunks, subject)
    process_figures(pdf, records, fig_dir, pid)
    review = []
    for r in records:
        r["paper_id"] = pid
        r["flags"] = validate_record(r)
        if r["flags"]:
            review.append((pid, r["q_no"], r["flags"]))
    paper_flags = validate_paper(records, printed_answers(pdf)) if records else ["no questions extracted"]
    review += [(pid, "PAPER", [f]) for f in paper_flags]
    usage = {k: sum(u.get(k, 0) or 0 for u in usages)
             for k in ("prompt_tokens", "output_tokens", "thinking_tokens", "total_tokens")}
    usage |= {"model": usages[0].get("model", ""), "cached": all(u.get("cached") for u in usages)}
    meta = {"exam_year": next((c.exam_year for c in chunks if c.exam_year), None),
            "paper_code": next((c.paper_code for c in chunks if c.paper_code), None)}
    (out_dir / f"{pid}.json").write_text(json.dumps(
        {"paper_id": pid, "subject": subject, **meta, "pages": len(pages), "paper_flags": paper_flags,
         "usage": usage, "questions": records}, ensure_ascii=False, indent=1), encoding="utf-8")
    return records, review, usage


def _worker(job):
    """Runs in a worker process; returns a tagged tuple so errors cross the process boundary."""
    pdf, out_dir, cache, fig_dir, subject = job
    t0 = time.time()
    try:
        rows, rev, usage = process_pdf(pdf, out_dir, cache, fig_dir, subject)
        return ("ok", pdf.stem, rows, rev, usage, time.time() - t0)
    except FatalAPIError as e:
        return ("fatal", pdf.stem, str(e), None, None, time.time() - t0)
    except RecitationBlocked as e:
        return ("skipped", pdf.stem, str(e), None, None, time.time() - t0)
    except Exception as e:  # noqa: BLE001  one bad PDF must not lose the rest of the batch
        return ("fail", pdf.stem, f"{type(e).__name__}: {str(e)[:200]}", None, None, time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--subject", default="chemistry", help="only chemistry has a chapter list so far")
    ap.add_argument("--workers", type=int, default=1, help="PDFs processed in parallel (separate processes)")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N PDFs (sorted by name)")
    ap.add_argument("--only", default=None, help="regex on the file name, e.g. 2018|2026")
    args = ap.parse_args()

    pdfs = sorted(args.pdf_dir.glob("**/*.pdf"))
    if args.only:
        pdfs = [p for p in pdfs if re.search(args.only, p.name)]
    if args.limit:
        pdfs = pdfs[: args.limit]
    args.out.mkdir(parents=True, exist_ok=True)
    cache, fig_dir = args.out / "cache", args.out / "figures"
    jobs = [(pdf, args.out, cache, fig_dir, args.subject) for pdf in pdfs]
    results, usage_rows, review = {}, [], []
    t_start = time.time()
    try:
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futs = {pool.submit(_worker, j): j[0].stem for j in jobs}
            for done, fut in enumerate(as_completed(futs), start=1):
                kind, pid, a, b, usage, secs = fut.result()
                prefix = f"[{done}/{len(jobs)}] {pid}"
                if kind != "ok":
                    review.append((pid, "PAPER", [f"{kind}: {a}"]))
                    print(f"{prefix}: {kind.upper()}: {a}")
                    if kind == "fatal":
                        for f in futs:
                            f.cancel()
                        break
                    continue
                results[pid] = (a, b)
                usage_rows.append({"paper_id": pid, **usage})
                print(f"{prefix} ({secs:.0f}s) {len(a)} questions, {len(b)} flags, "
                      f"tokens {usage['total_tokens']:,}{' (cached)' if usage.get('cached') else ''}")
    finally:
        usage_rows.sort(key=lambda r: r["paper_id"])
        write_usage(args.out, usage_rows)

    all_rows = []
    for pid in sorted(results):
        all_rows.extend(results[pid][0])
        review.extend(results[pid][1])
    with open(args.out / "all.jsonl", "w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(args.out / "review.md", "w", encoding="utf-8") as f:
        f.write(f"# Review queue ({len(review)} items)\n\n")
        for pid, qn, flags in review:
            f.write(f"- **{pid}** Q{qn}: " + "; ".join(flags) + "\n")
    print(f"Done in {(time.time() - t_start) / 60:.1f} min: {len(all_rows)} questions, "
          f"{len(review)} flagged -> {args.out}/review.md")


if __name__ == "__main__":
    main()
