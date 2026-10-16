"""Usage: python -m cbse_merge --out ./out/full [--merged-out ./out/full_merged]

Reads <out>/chemistry-*.json and writes one merged JSON per paper, all.jsonl and merge_report.md to
--merged-out (default <out>_merged). The input folder is never modified.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .merge import main_marks, merge_paper


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--merged-out", type=Path, default=None)
    args = ap.parse_args()
    dst = args.merged_out or Path(str(args.out).rstrip("/\\") + "_merged")
    dst.mkdir(parents=True, exist_ok=True)

    files = sorted(Path(args.out).glob("chemistry-*.json"))
    if not files:
        sys.exit(f"no chemistry-*.json in {args.out}")
    total = Counter()
    mism, rows, empty_stem = [], [], 0
    for f in files:
        paper = json.loads(f.read_text(encoding="utf-8"))
        merged, stats = merge_paper(paper)
        before, after = main_marks(paper), main_marks(merged)
        if abs(before - after) > 0.01:
            mism.append((paper["paper_id"], before, after))
        total.update(stats)
        total["records_before"] += len(paper["questions"])
        total["records_after"] += len(merged["questions"])
        total["flagged_before"] += sum(1 for q in paper["questions"] if q.get("flags"))
        total["flagged_after"] += sum(1 for q in merged["questions"] if q.get("flags"))
        total["with_stem"] += sum(1 for q in merged["questions"] if q.get("shared_stem"))
        for q in merged["questions"]:
            rows.append(q)
        (dst / f.name).write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(dst / "all.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    L = ["# Sub-part merge report", "",
         f"- papers: {len(files)}",
         f"- records: {total['records_before']} -> {total['records_after']}",
         f"- questions merged from sub-parts: {total['merged_questions']} "
         f"(from {total['merged_records_in']} records)",
         f"- shared stem detected and kept once: {total['with_stem']} questions",
         f"- part-level OR alternatives attached to their part: {total['or_attached_to_part']} records",
         f"- lone sub-part labels cleared (labels on OR alternatives): {total['lone_label_cleared']}",
         f"- records with flags: {total['flagged_before']} -> {total['flagged_after']}",
         f"- main-question marks identical in every paper: {'yes' if not mism else 'NO'}"]
    for pid, b, a in mism:
        L.append(f"  - {pid}: {b} -> {a}")
    (dst / "merge_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print(f"-> {dst}")


if __name__ == "__main__":
    main()
