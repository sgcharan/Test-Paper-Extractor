"""Usage:
    export GEMINI_API_KEY=...
    python -m cbse_extract.run --pdf-dir ./pdfs --out ./out [--structures]

Each PDF holds the questions followed by the answers / marking scheme at the end,
so every PDF is one paper (paper id = file name without extension).
"""
import argparse
import json
from pathlib import Path

from .gemini_client import extract
from .pdf_utils import build_parts, crop_figure
from .prompts import PAPER_PROMPT
from .schemas import Paper
from .validate import validate_paper, validate_record


def key(item: dict):
    return (str(item["q_no"]).strip(), (item.get("sub_part") or "").strip().lower(), item.get("or_alt", 0))


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--structures", action="store_true", help="try DECIMER image->SMILES (optional install)")
    args = ap.parse_args()

    pdfs = sorted(args.pdf_dir.glob("**/*.pdf"))

    args.out.mkdir(parents=True, exist_ok=True)
    cache = args.out / "cache"
    fig_dir = args.out / "figures"
    all_rows, review = [], []

    for pdf in pdfs:
        pid = pdf.stem
        print(f"== {pid}")
        parts, page_report = build_parts(pdf)
        paper = extract(pdf, parts, PAPER_PROMPT, Paper, cache)
        questions = [q.model_dump(mode="json") for q in paper.questions]
        answers = [a.model_dump(mode="json") for a in paper.answers]
        process_figures(pdf, questions, fig_dir, pid + "_q", args.structures)
        process_figures(pdf, answers, fig_dir, pid + "_a", args.structures)

        ans_by_key = {key(a): a for a in answers}
        used = set()
        for q in questions:
            a = ans_by_key.get(key(q))
            if a:
                used.add(key(q))
            q["answer"] = a
            q["paper_id"] = pid
            q["flags"] = validate_record(q)
            all_rows.append(q)
            if q["flags"]:
                review.append((pid, q["q_no"], q.get("sub_part"), q["flags"]))
        orphans = [a for k, a in ans_by_key.items() if k not in used]
        paper_flags = validate_paper(questions, orphans) if questions else ["no questions extracted"]
        for f in paper_flags:
            review.append((pid, "PAPER", None, [f]))

        (args.out / f"{pid}.json").write_text(json.dumps(
            {"paper_id": pid, "exam_year": paper.exam_year, "paper_code": paper.paper_code,
             "total_marks": paper.total_marks, "pages": page_report, "paper_flags": paper_flags,
             "questions": questions, "orphan_answers": orphans}, ensure_ascii=False, indent=1))

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
