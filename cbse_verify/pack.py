"""Layer 3: static HTML review pack (page crop next to the extracted record) and verdict scoring."""
import html
import json
import math
import random
import re
from collections import defaultdict
from pathlib import Path

import fitz

from . import checks

FIELDS = ["question", "options", "marks", "answer", "steps", "figure", "chapter"]


def _key(pid: str, q: dict) -> str:
    k = checks.rec_key(q)
    return f"{pid}|{k[0]}|{k[1]}|{k[2]}"


def select_records(papers: dict, findings: list, pct: float, seed: int = 7):
    """All records with an actionable finding, plus a stratified random sample of the others."""
    flagged = {}
    for f in findings:
        if f.bucket == "error" and f.q_no and (f.severity in ("high", "medium") or f.check in ("orphan", "validator")):
            flagged.setdefault(f"{f.paper}|{f.q_no}|{f.sub_part}|{f.or_alt}", []).append(f)
    strata = defaultdict(list)
    for pid, p in papers.items():
        modes = {x["page"]: x["mode"] for x in p.get("pages", [])}
        for q in p["questions"]:
            key = _key(pid, q)
            if key in flagged:
                continue
            strata[(checks.era(p.get("exam_year") or pid.split("-")[1]), modes.get(q.get("page"), "?"),
                    q.get("qtype"))].append((pid, q))
    rng = random.Random(seed)
    total = sum(len(v) for v in strata.values())
    want = max(150, math.ceil(total * pct / 100))
    sample = []
    for _, recs in sorted(strata.items(), key=lambda kv: str(kv[0])):
        n = max(1, round(want * len(recs) / max(1, total)))
        sample += rng.sample(recs, min(n, len(recs)))
    return flagged, sample[:want]


def _locate(doc, page_no: int, text: str):
    """y-range of the page where this text starts, or None."""
    if not (1 <= page_no <= len(doc)):
        return None
    ws = checks.words(text)[:5]
    for n in (5, 4, 3):
        if len(ws) >= n:
            hits = doc[page_no - 1].search_for(" ".join(ws[:n]))
            if hits:
                return hits[0].y0
    return None


def _image(doc, pid: str, page_no: int, y0, img_dir: Path) -> str | None:
    if not (1 <= page_no <= len(doc)):
        return None
    page = doc[page_no - 1]
    name = f"{pid}_p{page_no}" + (f"_y{int(y0)}" if y0 is not None else "") + ".jpg"
    path = img_dir / name
    if not path.exists():
        clip = None
        if y0 is not None:
            clip = fitz.Rect(0, max(0, y0 - 30), page.rect.width, min(page.rect.height, y0 + 330))
        page.get_pixmap(dpi=100 if clip else 70, clip=clip).save(path)
    return f"img/{name}"


_CSS = """body{font:14px system-ui,sans-serif;margin:16px;max-width:1500px}
.rec{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;border:1px solid #bbb;
border-radius:6px;margin:14px 0;padding:10px}.rec img{max-width:100%;border:1px solid #ddd;margin-bottom:6px}
.k{font-weight:600}pre{white-space:pre-wrap;background:#f6f6f6;padding:6px;border-radius:4px;margin:4px 0}
.find{color:#a40;font-size:13px}.src{color:#555;font-size:12px}label{margin-right:10px}
.bar{position:sticky;top:0;background:#fff;padding:6px 0;border-bottom:1px solid #ccc}
@media (prefers-color-scheme:dark){body{background:#161616;color:#ddd}pre{background:#222}.rec{border-color:#555}}"""

_JS = """
const P='cbse_verdict:';
function load(){document.querySelectorAll('.rec').forEach(r=>{try{const v=JSON.parse(localStorage.getItem(P+r.dataset.key)||'null');
 if(!v)return;r.querySelectorAll('input[value=ok],input[value=wrong]').forEach(i=>i.checked=(i.value===v.v));
 r.querySelectorAll('.fld').forEach(c=>c.checked=(v.fields||[]).includes(c.value));r.querySelector('.note').value=v.note||'';}catch(e){}});}
function save(r){const v=(r.querySelector('input[value=ok]:checked')||r.querySelector('input[value=wrong]:checked'));
 const o={v:v?v.value:null,fields:[...r.querySelectorAll('.fld:checked')].map(c=>c.value),note:r.querySelector('.note').value};
 try{localStorage.setItem(P+r.dataset.key,JSON.stringify(o));}catch(e){}}
document.addEventListener('change',e=>{const r=e.target.closest('.rec');if(r)save(r);});
document.addEventListener('input',e=>{const r=e.target.closest('.rec');if(r)save(r);});
function exportAll(){const out={};for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i);
 if(k.startsWith(P))out[k.slice(P.length)]=JSON.parse(localStorage.getItem(k));}
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:'application/json'}));
 a.download='verdicts.json';a.click();}
load();
"""


def _row(pid, q, why, imgs, kind) -> str:
    a = q.get("answer") or {}
    key = _key(pid, q)
    k = checks.rec_key(q)
    steps = "; ".join(f"{s['text'][:60]} [{s['marks']}]" for s in (a.get("steps") or []))
    opts = "<br>".join(html.escape(o) for o in (q.get("options") or []))
    flds = "".join(f'<label><input type="checkbox" class="fld" value="{f}">{f}</label>' for f in FIELDS)
    why_html = "".join(f"<div class='find'>[{html.escape(x.severity)}] {html.escape(x.check)}: "
                       f"{html.escape(x.detail)}</div>" for x in why)
    img_html = "".join(f'<div class="src">{html.escape(lbl)}</div><img src="{src}" loading="lazy">'
                       for lbl, src in imgs if src)
    return (f'<div class="rec" data-key="{html.escape(key)}"><div>{img_html or "<i>no page image</i>"}</div><div>'
            f'<div class="k">Q{html.escape(k[0])}{html.escape(k[1])}{" (OR)" if k[2] else ""} '
            f'&middot; {q.get("marks")} marks &middot; {html.escape(str(q.get("qtype")))} &middot; '
            f'{html.escape(str(q.get("chapter")))} &middot; {kind}</div>{why_html}'
            f'<pre>{html.escape(q.get("question_text") or "")}</pre>'
            + (f"<div class='k'>Options</div><pre>{opts}</pre>" if opts else "")
            + f"<div class='k'>Answer ({a.get('marks_total')} marks, p{a.get('page')})</div>"
              f"<pre>{html.escape(a.get('answer_text') or '(none)')}</pre>"
            + (f"<div class='src'>steps: {html.escape(steps)}</div>" if steps else "")
            + f'<div><label><input type="radio" name="{html.escape(key)}" value="ok">ok</label>'
              f'<label><input type="radio" name="{html.escape(key)}" value="wrong">wrong</label> {flds}</div>'
              f'<input class="note" placeholder="note" style="width:90%"></div></div>')


def build_pack(papers, pdfs, findings, vdir: Path, pct: float) -> int:
    pack = Path(vdir) / "review_pack"
    img_dir = pack / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    flagged, sample = select_records(papers, findings, pct)
    manifest = {}
    per_paper = defaultdict(list)
    for pid, p in papers.items():
        for q in p["questions"]:
            key = _key(pid, q)
            if key in flagged:
                per_paper[pid].append((q, flagged[key], "flagged"))
                manifest[key] = "flagged"
    for pid, q in sample:
        per_paper[pid].append((q, [], "random"))
        manifest[_key(pid, q)] = "random"
    index = []
    for pid, rows in sorted(per_paper.items()):
        doc = fitz.open(pdfs[pid]) if pid in pdfs else None
        body = []
        for q, why, kind in sorted(rows, key=lambda r: (r[0].get("page") or 0, str(r[0]["q_no"]))):
            imgs = []
            if doc is not None:
                a = q.get("answer") or {}
                qp = int(q.get("page") or 0)
                imgs.append((f"question, page {qp}", _image(doc, pid, qp, _locate(doc, qp, q.get("question_text") or ""), img_dir)))
                ap = int(a.get("page") or 0)
                if ap:
                    imgs.append((f"marking scheme, page {ap}",
                                 _image(doc, pid, ap, _locate(doc, ap, a.get("answer_text") or ""), img_dir)))
            body.append(_row(pid, q, why, imgs, kind))
        (pack / f"{pid}.html").write_text(
            f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>{html.escape(pid)}</title><style>{_CSS}</style>"
            f"<div class=bar><a href='index.html'>index</a> &middot; <b>{html.escape(pid)}</b> "
            f"<button onclick='exportAll()'>Export verdicts.json</button></div>{''.join(body)}<script>{_JS}</script>",
            encoding="utf-8")
        index.append((pid, len(rows), sum(1 for r in rows if r[2] == "flagged")))
    lines = "".join(f"<li><a href='{html.escape(pid)}.html'>{html.escape(pid)}</a> "
                    f"({n} records, {fl} flagged)</li>" for pid, n, fl in index)
    (pack / "index.html").write_text(
        f"<!doctype html><meta charset=utf-8><title>Review pack</title><style>{_CSS}</style>"
        f"<h2>Review pack: {sum(n for _, n, _ in index)} records in {len(index)} papers</h2>"
        f"<p>Mark each record ok or wrong. Verdicts are saved in your browser; use <b>Export verdicts.json</b> on any "
        f"paper page, then run <code>python -m cbse_verify --out ... --score verdicts.json</code>.</p><ul>{lines}</ul>",
        encoding="utf-8")
    (Path(vdir) / "pack_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return len(manifest)


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return 0.0, 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def score(verdicts_path: Path, papers: dict, vdir: Path | None = None) -> str:
    verdicts = json.loads(Path(verdicts_path).read_text(encoding="utf-8"))
    manifest = {}
    if vdir and (Path(vdir) / "pack_manifest.json").exists():
        manifest = json.loads((Path(vdir) / "pack_manifest.json").read_text(encoding="utf-8"))
    done = {k: v for k, v in verdicts.items() if v.get("v") in ("ok", "wrong")}
    L = [f"verdicts: {len(done)} records reviewed"]
    for kind, label in (("random", "random sample of unflagged records (unbiased estimate of the hidden error rate)"),
                        ("flagged", "flagged records (precision of the checks)")):
        sub = {k: v for k, v in done.items() if manifest.get(k) == kind}
        if sub:
            w = sum(1 for v in sub.values() if v["v"] == "wrong")
            p, lo, hi = wilson(w, len(sub))
            L.append(f"{label}: {w}/{len(sub)} wrong = {p:.1%} (95% CI {lo:.1%}-{hi:.1%})")
    wrong = [v for v in done.values() if v["v"] == "wrong"]
    if wrong:
        from collections import Counter
        c = Counter(f for v in wrong for f in v.get("fields", []))
        L.append("fields marked wrong: " + ", ".join(f"{f}={n}" for f, n in c.most_common()))
    return "\n".join(L)
