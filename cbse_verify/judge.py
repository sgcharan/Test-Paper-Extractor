"""Layer 2 (optional): ask a second, cheaper model to compare each paper's extracted JSON with its pages.

Uses its own cache folder under the verify output, so the extraction cache is never touched. Treat the output
as a hint for the review pack, not as ground truth.
"""
import json
import os
from pathlib import Path

import fitz
from pydantic import BaseModel, Field

from .checks import Finding, rec_key

PROMPT = """You are auditing a data extraction. Below is JSON that was extracted from the attached pages of a CBSE
Class 12 Chemistry question paper and its marking scheme. Compare it with the page images and report only
DEFINITE discrepancies: wrong numbers/values, wrong or missing words, wrong marks, wrong answer, missing or extra
options, a question or part that is not in the JSON, steps whose marks do not match the scheme. Do not report
style or formatting. Chemistry may be written in LaTeX/mhchem; that is fine. If everything matches, return no issues.

EXTRACTED JSON:
"""


class Issue(BaseModel):
    q_no: str
    sub_part: str = ""
    or_alt: int = 0
    field: str = Field(description="question | options | marks | answer | steps | missing")
    problem: str
    evidence: str = Field(description="what the page actually shows")


class Report(BaseModel):
    issues: list[Issue] = Field(default_factory=list)


def run_judge(papers: dict, pdfs: dict, vdir: Path, model: str = "gemini-3.5-flash-lite") -> list[Finding]:
    os.environ.setdefault("GEMINI_MODEL", model)
    from google.genai import types
    from cbse_extract.gemini_client import FatalAPIError, RecitationBlocked, extract

    cache = Path(vdir) / "judge_cache"
    out: list[Finding] = []
    for i, (pid, p) in enumerate(papers.items(), 1):
        pdf = pdfs.get(pid)
        if pdf is None:
            continue
        pages = sorted({int(q["page"]) for q in p["questions"] if q.get("page")} |
                       {int(q["answer"]["page"]) for q in p["questions"] if q.get("answer") and q["answer"].get("page")})
        doc = fitz.open(pdf)
        parts = []
        for pg in pages:
            if 1 <= pg <= len(doc):
                parts.append(f"=== PAGE {pg} ===")
                parts.append(types.Part.from_bytes(
                    data=doc[pg - 1].get_pixmap(dpi=110).tobytes("jpeg", jpg_quality=80), mime_type="image/jpeg"))
        recs = [{"q_no": q["q_no"], "sub_part": q.get("sub_part"), "or_alt": q.get("or_alt"), "marks": q.get("marks"),
                 "page": q.get("page"), "question": q.get("question_text"), "options": q.get("options"),
                 "answer": (q.get("answer") or {}).get("answer_text"),
                 "steps": [(s["text"][:80], s["marks"]) for s in ((q.get("answer") or {}).get("steps") or [])],
                 "scheme_marks": (q.get("answer") or {}).get("marks_total")} for q in p["questions"]]
        prompt = PROMPT + json.dumps(recs, ensure_ascii=False)
        try:
            rep, usage = extract(pdf, parts, prompt, Report, cache)
        except (RecitationBlocked, FatalAPIError) as e:
            print(f"  judge skipped {pid}: {str(e)[:100]}")
            if isinstance(e, FatalAPIError):
                break
            continue
        print(f"  judge [{i}/{len(papers)}] {pid}: {len(rep.issues)} issues, {usage.get('total_tokens', 0):,} tokens")
        for it in rep.issues:
            out.append(Finding(pid, it.q_no, it.sub_part, it.or_alt, it.field, "judge", "medium", "error",
                               f"{it.problem} | page shows: {it.evidence}"[:400]))
    return out
