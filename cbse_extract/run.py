"""Usage:
    export GEMINI_API_KEY=...
    python -m cbse_extract.run --pdf-dir ./pdfs --out ./out [--structures]

Naming: put 'qp' or 'ms' (or 'marking scheme') in the filename, e.g.
    2024_set1_qp.pdf  +  2024_set1_ms.pdf   -> one paper "2024_set1"
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from .gemini_client import extract
from .pdf_utils import build_parts, crop_figure
from .prompts import MS_PROMPT, QP_PROMPT
from .schemas import MarkingScheme, QuestionPaper
from .validate import validate_paper, validate_record

KIND_RE = re.compile(r"(^|[_\-\s])(ms|marking[_\-\s]?scheme|marking|scheme)([_\-\s]|$)", re.I)
STRIP_RE = re.compile(r"[_\-\s]*(ms|qp|marking[_\-\s]?scheme|marking|scheme|question[_\-\s]?paper)[_\-\s]*", re.I)


def kind_of(p: Path) -> str:
    return "ms" if KIND_RE.search(p.stem) else "qp"


def paper_id(p: Path) -> str:
    return STRIP_RE.sub("_", p.stem).strip("_") or p.stem


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

    groups = defaultdict(dict)
    for pdf in sorted(args.pdf_dir.glob("**/*.pdf")):
        groups[paper_id(pdf)][kind_of(pdf)] = pdf

    args.out.mkdir(parents=True, exist_ok=True)
    cache = args.out / "cache"
    fig_dir = args.out / "figures"
    all_rows, review = [], []

    for pid, files in groups.items():
        print(f"== {pid}  ({', '.join(files)})")
        questions, answers, page_report = [], [], {}

        if "qp" in files:
            parts, page_report["qp"] = build_parts(files["qp"])
            qp = extract(files["qp"], parts, QP_PROMPT, QuestionPaper, cache)
            questions = [q.model_dump(mode="json") for q in qp.items]
            process_figures(files["qp"], questions, fig_dir, pid + "_qp", args.structures)
        if "ms" in files:
            parts, page_report["ms"] = build_parts(files["ms"])
            ms = extract(files["ms"], parts, MS_PROMPT, MarkingScheme, cache)
            answers = [a.model_dump(mode="json") for a in ms.items]
            process_figures(files["ms"], answers, fig_dir, pid + "_ms", args.structures)

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
        paper_flags = validate_paper(questions, orphans) if questions else ["no question paper file found"]
        for f in paper_flags:
            review.append((pid, "PAPER", None, [f]))

        (args.out / f"{pid}.json").write_text(json.dumps(
            {"paper_id": pid, "pages": page_report, "paper_flags": paper_flags,
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
