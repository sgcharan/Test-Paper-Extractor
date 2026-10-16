"""Usage:
    python -m cbse_verify --out ./out/full --pdf-dir <dir> [<dir> ...]
        [--verify-out ./out/full_verify] [--sample 4] [--llm-check] [--selftest]
    python -m cbse_verify --out ./out/full --score verdicts.json

Read-only with respect to --out and the PDFs; every file written goes under --verify-out.
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from . import checks


def write_findings(vdir: Path, findings: list[checks.Finding]):
    cols = ["paper", "q_no", "sub_part", "or_alt", "field", "check", "severity", "bucket", "detail"]
    with open(vdir / "verify_findings.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for fd in sorted(findings, key=lambda x: (x.bucket, x.severity != "high", x.paper, x.q_no)):
            w.writerow(fd.row())


def write_report(vdir: Path, papers: dict, findings: list[checks.Finding], sampled: int | None):
    errs = [f for f in findings if f.bucket == "error"]
    anom = [f for f in findings if f.bucket == "source_anomaly"]
    recs = sum(len(p["questions"]) for p in papers.values())
    flagged = {(f.paper, f.q_no, f.sub_part, f.or_alt) for f in errs if f.q_no}
    L = ["# Verification report", "",
         f"- papers: {len(papers)}, records: {recs}",
         f"- findings: {len(errs)} error candidates on {len(flagged)} records "
         f"({len(flagged) / max(1, recs):.1%} of records), {len(anom)} source anomalies", ""]
    L += ["## Error candidates by check and severity", "", "| check | high | medium | low |", "|---|---|---|---|"]
    for ck in sorted({f.check for f in errs}):
        c = Counter(f.severity for f in errs if f.check == ck)
        L.append(f"| {ck} | {c['high']} | {c['medium']} | {c['low']} |")
    L += ["", "## Papers with the most high/medium findings", ""]
    per = Counter(f.paper for f in errs if f.severity in ("high", "medium"))
    for pid, n in per.most_common(15):
        L.append(f"- {pid}: {n}")
    if sampled is not None:
        L += ["", f"## Human review pack", "", f"{sampled} records selected (all error candidates plus a "
              "stratified random sample). Open `review_pack/index.html`."]
    L += ["", "## Source anomalies (not extraction errors)", ""]
    for f in anom[:40]:
        L.append(f"- {f.paper} Q{f.q_no}{f.sub_part}: {f.detail}")
    (vdir / "verify_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True, help="extraction output folder (read only)")
    ap.add_argument("--pdf-dir", type=Path, nargs="*", default=[], help="folders containing the source PDFs")
    ap.add_argument("--verify-out", type=Path, default=None, help="default: <out>_verify")
    ap.add_argument("--sample", type=float, default=4.0, help="percent of unflagged records added to the pack")
    ap.add_argument("--llm-check", action="store_true", help="optional second-model judge (costs tokens)")
    ap.add_argument("--selftest", action="store_true", help="corrupt copies of records and measure detection")
    ap.add_argument("--score", type=Path, default=None, help="verdicts.json exported from the review pack")
    ap.add_argument("--no-pack", action="store_true")
    args = ap.parse_args()

    vdir = args.verify_out or Path(str(args.out).rstrip("/\\") + "_verify")
    vdir.mkdir(parents=True, exist_ok=True)
    papers = checks.load_papers(args.out)
    if not papers:
        sys.exit(f"no chemistry-*.json found in {args.out}")

    if args.score:
        from .pack import score
        print(score(args.score, papers, vdir))
        return

    pdfs = checks.index_pdfs(args.pdf_dir)
    print(f"{len(papers)} papers, {len(pdfs)} PDFs indexed")
    findings = checks.run_checks(papers, pdfs,
                                 progress=lambda i, n, pid: print(f"\r[{i}/{n}] {pid[:60]:60}", end="", flush=True))
    print()

    if args.llm_check:
        from .judge import run_judge
        findings += run_judge(papers, pdfs, vdir)

    write_findings(vdir, findings)
    sampled = None
    if not args.no_pack:
        from .pack import build_pack
        sampled = build_pack(papers, pdfs, findings, vdir, args.sample)
    write_report(vdir, papers, findings, sampled)
    errs = [f for f in findings if f.bucket == "error"]
    print(f"{len(errs)} error candidates, {len(findings) - len(errs)} source anomalies -> {vdir}")

    if args.selftest:
        from .selftest import run_selftest
        print(run_selftest(papers, pdfs, findings))


if __name__ == "__main__":
    main()
