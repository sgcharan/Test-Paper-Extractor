"""Layer 1: free, deterministic checks of extracted records against the source PDF text layer."""
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path

import fitz  # PyMuPDF (already a dependency of cbse_extract)

from cbse_extract.pdf_utils import english_only, text_is_reliable
from cbse_extract.validate import validate_record

# Notes in the marking scheme that explain a marks/answer oddity: the paper itself is inconsistent.
SOURCE_NOTE_RE = re.compile(
    r"printing error|is deleted|deleted because|marks? .{0,40}merged", re.I)
_SUBSUP = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻−–", "01234567890123456789+---")
_LATEX_CMD = re.compile(r"\\[A-Za-z]+")
_TOKEN = re.compile(r"[a-z]+|\d+(?:\.\d+)?")


def tokens(text: str) -> list[str]:
    """Letters and numbers only, so garbled spacing/subscripts in the text layer do not matter."""
    t = (text or "").translate(_SUBSUP).replace("\\cdot", ".").replace("·", ".").replace("[FIGURE]", " ")
    t = _LATEX_CMD.sub(" ", t)
    t = re.sub(r"[{}$^_\\]", " ", t)
    return _TOKEN.findall(t.lower())


def words(text: str) -> list[str]:
    """Prose words only (>=4 letters). Formulas and equations are often images or garbled legacy-font text in
    these PDFs, so they are not a reliable anchor; ordinary words are."""
    return [t for t in tokens(text) if len(t) >= 4 and t.isalpha()]


def era(year) -> str:
    try:
        y = int(str(year)[:4])
    except ValueError:
        return "term"
    return "<=2016" if y <= 2016 else ("2017-2022" if y <= 2022 else "2023+")


def group_key(paper_id: str) -> str:
    """Papers that are sets of the same exam share most questions (set 1/2/3, 56/1/1..3, 5611..5613)."""
    s = paper_id.replace("chemistry-", "", 1)
    s = re.sub(r"-set-[–\-]*-?\d+$", "", s)
    s = re.sub(r"-\d$", "", s)
    s = re.sub(r"(?<=\d{3})\d$", "", s)
    return s


@dataclass
class Finding:
    paper: str
    q_no: str
    sub_part: str
    or_alt: int
    field: str      # question | answer | options | marks | steps | coverage | paper
    check: str      # anchor | numbers | coverage | consensus | options | validator | orphan | pattern
    severity: str   # high | medium | low
    bucket: str     # error | source_anomaly
    detail: str

    def row(self):
        return asdict(self)


def rec_key(q: dict) -> tuple:
    return (str(q["q_no"]), q.get("sub_part") or "", int(q.get("or_alt") or 0))


def load_papers(out_dir: Path) -> dict[str, dict]:
    papers = {}
    for f in sorted(Path(out_dir).glob("chemistry-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        papers[d["paper_id"]] = d
    return papers


def index_pdfs(pdf_dirs: list[Path]) -> dict[str, Path]:
    idx = {}
    for d in pdf_dirs:
        for p in Path(d).glob("**/*.pdf"):
            idx.setdefault(p.stem, p)
    return idx


class PageText:
    """English text and token sets per page of one PDF (lazy)."""

    def __init__(self, pdf: Path):
        self.doc = fitz.open(pdf)
        self.n = len(self.doc)
        self._text: dict[int, str] = {}

    def text(self, page: int) -> str:
        if page not in self._text:
            self._text[page] = english_only(self.doc[page - 1].get_text("text")) if 1 <= page <= self.n else ""
        return self._text[page]

    def reliable(self, page: int) -> bool:
        return text_is_reliable(self.text(page))

    def all_tokens(self) -> set:
        if not hasattr(self, "_all"):
            self._all = set()
            for p in range(1, self.n + 1):
                self._all.update(tokens(self.text(p)))
        return self._all

    def has_images(self, page: int) -> bool:
        return 1 <= page <= self.n and bool(self.doc[page - 1].get_images())

    def window(self, page: int, spread: int = 1):
        """Union token set and text of pages page-spread..page+spread that have a reliable text layer."""
        toks, txt, used = set(), [], []
        for p in range(max(1, page - spread), min(self.n, page + spread) + 1):
            if self.reliable(p):
                t = self.text(p)
                toks.update(tokens(t))
                txt.append(t)
                used.append(p)
        return toks, "\n".join(txt), used


def _record_texts(q: dict):
    a = q.get("answer") or {}
    yield "question", q.get("question_text") or "", q.get("page")
    if q.get("options"):
        yield "options", " ".join(q["options"]), q.get("page")
    if a:
        yield "answer", a.get("answer_text") or "", a.get("page")


def check_anchoring(paper: dict, pages: PageText) -> list[Finding]:
    """Words must exist somewhere in the source text; numbers must exist on the record's own page.

    Word recall is measured against the whole document (a question may run onto the next page or sit on a
    page mislabelled by one). A page with embedded images may hide text (case passages, equations), so those
    findings are downgraded to low.
    """
    out = []
    doc_tokens = pages.all_tokens()
    for q in paper["questions"]:
        k = rec_key(q)
        short_answer = q.get("qtype") in ("mcq", "assertion_reason")
        for field, text, page in _record_texts(q):
            if not page:
                continue
            if field == "answer" and short_answer:
                continue  # scheme gives only the option letter; the stored answer_text is the expanded option
            page = int(page)
            imgs = any(pages.has_images(p) for p in (page - 1, page, page + 1))
            w = words(text)
            if len(w) >= 6 and len(doc_tokens) > 200:
                recall = sum(1 for t in w if t in doc_tokens) / len(w)
                thr = 0.55 if field == "answer" else 0.80
                if recall < thr:
                    miss = [t for t in dict.fromkeys(w) if t not in doc_tokens][:8]
                    sev = "low" if imgs else ("high" if recall < 0.4 else "medium")
                    out.append(Finding(paper["paper_id"], k[0], k[1], k[2], field, "anchor", sev, "error",
                                       f"only {recall:.0%} of words appear anywhere in the source text; e.g. {miss}"
                                       + (" (page has embedded images: text may be unextractable)" if imgs else "")))
            if field in ("question", "options") and len(doc_tokens) > 200:
                odd = [t for t in dict.fromkeys(w) if len(t) >= 6 and t not in doc_tokens]
                if odd and len(odd) <= 4:  # a few unknown words = typo/hallucination; many = text is an image
                    out.append(Finding(paper["paper_id"], k[0], k[1], k[2], field, "words",
                                       "low" if imgs else "medium", "error",
                                       f"word(s) not found anywhere in the source text: {odd}"))
            src_tokens, _, used = pages.window(page)
            if not used:
                continue
            nums = [t for t in tokens(text) if re.fullmatch(r"\d+\.\d+|\d{3,}", t)]
            gone = [n for n in dict.fromkeys(nums) if n not in src_tokens]
            if gone and field in ("question", "options"):
                out.append(Finding(paper["paper_id"], k[0], k[1], k[2], field, "numbers",
                                   "low" if imgs else "high", "error",
                                   f"numbers not on page {page}: {gone[:6]}"))
            elif len(gone) >= 3 and field == "answer":
                out.append(Finding(paper["paper_id"], k[0], k[1], k[2], field, "numbers", "low", "error",
                                   f"answer numbers not on page {page}: {gone[:6]}"))
    return out


def check_coverage(paper: dict, pages: PageText) -> list[Finding]:
    """Question-number headings on question pages that no record covers (possibly missed questions)."""
    qs = paper["questions"]
    have = {str(q["q_no"]) for q in qs}
    nums = [int(q["q_no"]) for q in qs if str(q["q_no"]).isdigit()]
    if not nums:
        return []
    ans_pages = [q["answer"]["page"] for q in qs if q.get("answer") and q["answer"].get("page")]
    last_q_page = max((q["page"] for q in qs if q.get("page")), default=0)
    first_ans = min(ans_pages) if ans_pages else last_q_page + 1
    found = set()
    for p in range(1, min(first_ans, pages.n + 1)):
        if not pages.reliable(p):
            continue
        for m in re.finditer(r"(?m)^\s*(\d{1,2})\.\s+\S", pages.text(p)):
            n = int(m.group(1))
            if 1 <= n <= max(nums):
                found.add(n)
    missing = sorted(n for n in found if str(n) not in have)
    return [Finding(paper["paper_id"], str(n), "", 0, "coverage", "coverage", "medium", "error",
                    "question number appears as a heading in the source but has no record") for n in missing]


def check_internal(paper: dict) -> list[Finding]:
    """Re-run the pipeline validators and classify each result as an error or a source anomaly."""
    out = []
    pid = paper["paper_id"]
    # a note on one sub-part ("part (ii) deleted, marks given to (i) and (iii)") explains its siblings too
    noted = {(str(q["q_no"]), int(q.get("or_alt") or 0)) for q in paper["questions"]
             if q.get("answer") and SOURCE_NOTE_RE.search(q["answer"].get("answer_text") or "")}
    for q in paper["questions"]:
        k = rec_key(q)
        a = q.get("answer") or {}
        note = (k[0], k[2]) in noted
        for fl in validate_record(q):
            diff = re.search(r"sum ([\d.]+) != question marks ([\d.]+)", fl)
            half = bool(diff and abs(float(diff.group(1)) - float(diff.group(2))) in (0.5, 1.0))
            bucket = "source_anomaly" if note else "error"
            out.append(Finding(pid, k[0], k[1], k[2], "marks" if "marks" in fl else "answer", "validator",
                               "low" if bucket == "source_anomaly" else "medium", bucket,
                               fl + (" (steps probably missing a mark)" if half and "step marks" in fl else "")))
    for o in paper.get("orphan_answers", []):
        out.append(Finding(pid, str(o["q_no"]), o.get("sub_part") or "", int(o.get("or_alt") or 0), "answer",
                           "orphan", "medium", "error", "marking-scheme entry matched no question"))
    return out


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def check_consensus(papers: dict[str, dict]) -> list[Finding]:
    """Sets of the same exam share most questions: compare marks, options and answers across sets."""
    groups = defaultdict(list)
    for pid in papers:
        groups[group_key(pid)].append(pid)
    out = []
    for gk, pids in groups.items():
        if len(pids) < 2:
            continue
        recs = []  # (paper, key, token set, record)
        for pid in pids:
            for q in papers[pid]["questions"]:
                ts = set(tokens(q.get("question_text") or ""))
                if len(ts) >= 6:
                    recs.append((pid, rec_key(q), ts, q))
        parent = list(range(len(recs)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                if recs[i][0] != recs[j][0] and _jaccard(recs[i][2], recs[j][2]) >= 0.85:
                    parent[find(i)] = find(j)
        clusters = defaultdict(list)
        for i in range(len(recs)):
            clusters[find(i)].append(recs[i])
        for members in clusters.values():
            if len({m[0] for m in members}) < 2:
                continue
            _compare_cluster(members, out)
    return out


def _compare_cluster(members, out):
    """members: (paper, key, question token set, record). Disagreements are medium/high only when the question
    text is (almost) identical across sets; otherwise the sets carry a variant of the question (different
    values/options) and a difference is expected."""
    def same_question(m):
        others = [o for o in members if o[0] != m[0]]
        return bool(others) and max(_jaccard(m[2], o[2]) for o in others) >= 0.97

    def vote(extract, label, field, sev):
        vals = [extract(m[3]) for m in members]
        cnt = Counter(v for v in vals if v is not None)
        if len(cnt) < 2:
            return
        top, topn = cnt.most_common(1)[0]
        for m, v in zip(members, vals):
            if v is None or v == top:
                continue
            tie = topn == 1
            level = sev if (not tie and same_question(m)) else "low"
            out.append(Finding(m[0], m[1][0], m[1][1], m[1][2], field, "consensus", level, "error",
                               f"{label} differs between sets: {v!r} here vs {top!r} in {topn} other"
                               + (" (no majority)" if tie else "")))

    vote(lambda r: r.get("marks"), "marks", "marks", "high")
    vote(lambda r: tuple(sorted(set(tokens(" ".join(r["options"]))))) if r.get("options") else None,
         "options", "options", "medium")
    ans = [(m, set(tokens((m[3].get("answer") or {}).get("answer_text") or ""))) for m in members]
    ans = [(m, t) for m, t in ans if len(t) >= 3]
    for i, (m, t) in enumerate(ans):
        sims = [_jaccard(t, ot) for j, (o, ot) in enumerate(ans) if j != i and o[0] != m[0]]
        if sims and max(sims) < 0.5:
            out.append(Finding(m[0], m[1][0], m[1][1], m[1][2], "answer", "consensus",
                               "medium" if same_question(m) else "low", "error",
                               f"answer differs from the same question in {len(sims)} other set(s) "
                               f"(best overlap {max(sims):.0%})"))


def run_checks(papers: dict[str, dict], pdfs: dict[str, Path], progress=None) -> list[Finding]:
    findings: list[Finding] = []
    for i, (pid, paper) in enumerate(papers.items(), 1):
        if progress:
            progress(i, len(papers), pid)
        findings += check_internal(paper)
        pdf = pdfs.get(pid)
        if pdf is None:
            findings.append(Finding(pid, "", "", 0, "paper", "anchor", "low", "error", "source PDF not found"))
            continue
        pages = PageText(pdf)
        findings += check_anchoring(paper, pages)
        findings += check_coverage(paper, pages)
    findings += check_consensus(papers)
    # one record can trip several checks: keep every finding but drop exact duplicates
    seen, uniq = set(), []
    for f in findings:
        k = (f.paper, f.q_no, f.sub_part, f.or_alt, f.field, f.check, f.detail)
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq
