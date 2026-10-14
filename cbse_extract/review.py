"""Build a local HTML page to check extracted questions against the source PDFs.

    python -m cbse_extract.review --pdf-dir ./pdfs --out ./out [--sample 0.1] [--seed 0]
    python -m cbse_extract.review --apply reviewed.json --out ./out

Shows every flagged question plus a random sample of the rest (the sample estimates the error rate
among questions nobody flagged). Open out/review/index.html in a browser.
"""
import argparse
import json
import os
import random
from pathlib import Path

import fitz  # PyMuPDF

from .pdf_utils import english_only, text_is_reliable
from .validate import text_layer_similarity

PAGE_DPI = 110
MATCH_THRESHOLD = 0.6


def row_key(r: dict) -> str:
    return "|".join([str(r["paper_id"]), str(r["q_no"]).strip(), (r.get("sub_part") or "").strip().lower(),
                     str(r.get("or_alt", 0))])


def load_rows(out: Path) -> list[dict]:
    with open(out / "all.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def select_rows(rows: list[dict], sample: float, seed: int) -> list[dict]:
    """Flagged rows always; a seeded random fraction of the unflagged ones, tagged 'sample'."""
    flagged = [r for r in rows if r.get("flags")]
    clean = [r for r in rows if not r.get("flags")]
    n = min(len(clean), max(1, round(len(clean) * sample))) if clean and sample > 0 else 0
    picked = random.Random(seed).sample(clean, n)
    for r in flagged:
        r["_why"] = "flagged"
    for r in picked:
        r["_why"] = "sample"
    order = lambda r: (r["paper_id"], str(r["q_no"]).zfill(4), r.get("sub_part") or "", r.get("or_alt", 0))
    return sorted(flagged, key=order) + sorted(picked, key=order)


def add_text_match_flags(rows: list[dict], pdf_dir: Path):
    """Flag questions whose words are mostly absent from the page's text layer (digital pages only)."""
    docs, cache = {}, {}
    pdfs = {p.stem: p for p in pdf_dir.glob("**/*.pdf")}
    for r in rows:
        pdf = pdfs.get(r["paper_id"])
        if not pdf or not r.get("page"):
            continue
        k = (r["paper_id"], r["page"])
        if k not in cache:
            doc = docs.setdefault(r["paper_id"], fitz.open(pdf))
            text = english_only(doc[r["page"] - 1].get_text("text")) if 1 <= r["page"] <= len(doc) else ""
            cache[k] = text if text_is_reliable(text) else None
        if cache[k] is None:
            continue
        sim = text_layer_similarity(r["question_text"], cache[k])
        r["text_match"] = round(sim, 2)
        if sim < MATCH_THRESHOLD:
            r.setdefault("flags", []).append(f"low text-layer match ({sim:.2f})")
            r["_why"] = "flagged"


def render_pages(rows: list[dict], pdf_dir: Path, pages_dir: Path):
    pages_dir.mkdir(parents=True, exist_ok=True)
    pdfs = {p.stem: p for p in pdf_dir.glob("**/*.pdf")}
    need = set()
    for r in rows:
        need.add((r["paper_id"], r.get("page")))
        if r.get("answer"):
            need.add((r["paper_id"], r["answer"].get("page")))
    docs = {}
    for pid, page in sorted(need, key=lambda x: (x[0], x[1] or 0)):
        dest = pages_dir / f"{pid}_p{page}.jpg"
        if not page or dest.exists() or pid not in pdfs:
            continue
        doc = docs.setdefault(pid, fitz.open(pdfs[pid]))
        if 1 <= page <= len(doc):
            doc[page - 1].get_pixmap(dpi=PAGE_DPI).save(dest, jpg_quality=80)


def slim(r: dict) -> dict:
    a = r.get("answer") or {}
    return {"key": row_key(r), "paper": r["paper_id"], "q_no": r["q_no"], "sub_part": r.get("sub_part"),
            "or_alt": r.get("or_alt", 0), "why": r["_why"], "flags": r.get("flags", []), "page": r.get("page"),
            "marks": r.get("marks"), "section": r.get("section"), "qtype": r.get("qtype"),
            "chapter": r.get("chapter"), "level": r.get("cognitive_level"), "text": r["question_text"],
            "options": r.get("options"), "figures": [f.get("crop_path") for f in r.get("figures", []) if f.get("crop_path")],
            "ans": {"page": a.get("page"), "text": a.get("answer_text", ""), "marks": a.get("marks_total"),
                    "steps": a.get("steps") or [],
                    "figures": [f.get("crop_path") for f in a.get("figures", []) if f.get("crop_path")]} if a else None}


def build_html(items: list[dict], out: Path) -> Path:
    rel = lambda p: Path(os.path.relpath(Path(p).resolve(), (out / "review").resolve())).as_posix() if p else None
    for it in items:
        it["figures"] = [rel(p) for p in it["figures"]]
        if it["ans"]:
            it["ans"]["figures"] = [rel(p) for p in it["ans"]["figures"]]
    html = HTML.replace("__DATA__", json.dumps(items, ensure_ascii=False).replace("</", "<\\/"))
    dest = out / "review" / "index.html"
    dest.write_text(html, encoding="utf-8")
    return dest


def apply_decisions(decisions_path: Path, out: Path) -> Path:
    """Merge reviewed.json into a new all.reviewed.jsonl; the original all.jsonl is untouched."""
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    rows = load_rows(out)
    dest = out / "all.reviewed.jsonl"
    counts = {"accepted": 0, "edited": 0, "rejected": 0, "unreviewed": 0}
    with open(dest, "w", encoding="utf-8") as f:
        for r in rows:
            d = decisions.get(row_key(r))
            if not d:
                r["verified"] = None
                counts["unreviewed"] += 1
            else:
                r["verified"] = d["status"] != "rejected"
                if d["status"] == "edited":
                    edit = d.get("edit", {})
                    if "text" in edit:
                        r["question_text"] = edit["text"]
                    if "marks" in edit and edit["marks"] not in (None, ""):
                        r["marks"] = float(edit["marks"])
                    if "ans_text" in edit and r.get("answer"):
                        r["answer"]["answer_text"] = edit["ans_text"]
                r["review_status"] = d["status"]
                counts[d["status"]] += 1
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Wrote {dest}: {counts}")
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pdf-dir", type=Path)
    ap.add_argument("--sample", type=float, default=0.1, help="fraction of unflagged questions to include")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--apply", type=Path, help="reviewed.json exported from the page")
    args = ap.parse_args()

    if args.apply:
        apply_decisions(args.apply, args.out)
        return
    if not args.pdf_dir:
        ap.error("--pdf-dir is required unless --apply is used")
    rows = load_rows(args.out)
    add_text_match_flags(rows, args.pdf_dir)
    chosen = select_rows(rows, args.sample, args.seed)
    render_pages(chosen, args.pdf_dir, args.out / "review" / "pages")
    dest = build_html(list(map(slim, chosen)), args.out)
    n_flag = sum(r["_why"] == "flagged" for r in chosen)
    print(f"{len(chosen)} of {len(rows)} questions to review ({n_flag} flagged, {len(chosen) - n_flag} sampled) -> {dest}")


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dataset Review</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css">
<style>
:root{--bg:#f6f7f9;--fg:#1c2128;--card:#fff;--line:#d8dde3;--mut:#5d6773;--ok:#1a7f37;--bad:#cf222e;--warn:#9a6700;--acc:#0969da}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--card:#161b22;--line:#30363d;--mut:#8b949e;--ok:#3fb950;--bad:#f85149;--warn:#d29922;--acc:#58a6ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
header{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;padding:8px 16px;background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:2}
header select,header button{font:inherit;padding:3px 8px;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px}
main{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px;align-items:start}
@media (max-width:900px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}
.tabs button{margin-right:6px}.tabs button.on{border-color:var(--acc);color:var(--acc)}
.page img{width:100%;border:1px solid var(--line);border-radius:4px}
.flag{color:var(--warn)}.meta{color:var(--mut);font-size:13px}.tag{display:inline-block;padding:0 8px;border-radius:10px;border:1px solid var(--line);font-size:12px}
.status-accepted{color:var(--ok)}.status-rejected{color:var(--bad)}.status-edited{color:var(--acc)}
.txt{white-space:pre-wrap}.figs img{max-width:100%;max-height:200px;margin:4px 4px 0 0;border:1px solid var(--line)}
textarea{width:100%;min-height:90px;font:inherit;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px}
.actions button{padding:6px 14px;margin-right:6px;cursor:pointer}
.opts{margin:6px 0 0;padding-left:20px}
</style></head><body>
<header>
<strong id="pos"></strong>
<label>Show <select id="filter"><option value="all">all</option><option value="todo">undecided</option><option value="flagged">flagged</option><option value="sample">sample</option></select></label>
<span id="stats" class="meta"></span>
<button id="export">Export decisions</button>
<span class="meta">a accept · x reject · e edit · j/k next/prev</span>
</header>
<main>
<section class="card page"><div class="tabs"><button id="tq" class="on">Question page</button><button id="ta">Answer page</button></div><p class="meta" id="pgno"></p><img id="pageimg" alt="PDF page"></section>
<section class="card"><div id="detail"></div></section>
</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/contrib/mhchem.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/contrib/auto-render.min.js"></script>
<script>
const ITEMS = __DATA__;
const LS = "cbse-review-decisions";
let decisions = {};
try { decisions = JSON.parse(localStorage.getItem(LS) || "{}"); } catch (e) {}
const save = () => { try { localStorage.setItem(LS, JSON.stringify(decisions)); } catch (e) {} };
let idx = 0, tab = "q", editing = false;
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
function wrapCe(s) {  // bare \ce{...} outside $...$ -> $\ce{...}$
  return s.split("$").map((seg, i) => {
    if (i % 2) return seg;
    let out = "", p = 0, m;
    const re = /\\ce\{/g;
    while ((m = re.exec(seg))) {
      let d = 1, j = re.lastIndex;
      while (j < seg.length && d) { d += seg[j] === "{" ? 1 : seg[j] === "}" ? -1 : 0; j++; }
      out += seg.slice(p, m.index) + "$" + seg.slice(m.index, j) + "$"; p = j; re.lastIndex = j;
    }
    return out + seg.slice(p);
  }).join("$");
}
const tex = s => esc(wrapCe(s || ""));
const visible = () => ITEMS.map((it, i) => i).filter(i => {
  const f = $("filter").value, it = ITEMS[i], d = decisions[it.key];
  return f === "all" || (f === "todo" && !d) || (f === "flagged" && it.why === "flagged") || (f === "sample" && it.why === "sample");
});
function stats() {
  const s = ITEMS.filter(i => i.why === "sample"), rev = s.filter(i => decisions[i.key]);
  const bad = rev.filter(i => decisions[i.key].status !== "accepted").length;
  const done = ITEMS.filter(i => decisions[i.key]).length;
  $("stats").textContent = `${done}/${ITEMS.length} reviewed · sample error rate: ` +
    (rev.length ? `${bad}/${rev.length} (${Math.round(100 * bad / rev.length)}%)` : "n/a");
}
function show() {
  const vis = visible();
  if (!vis.length) { $("detail").textContent = "Nothing to show for this filter."; $("pos").textContent = "0/0"; stats(); return; }
  if (!vis.includes(idx)) idx = vis.find(i => i >= idx) ?? vis[vis.length - 1];
  const it = ITEMS[idx], d = decisions[it.key];
  $("pos").textContent = `${vis.indexOf(idx) + 1}/${vis.length} · ${it.paper} Q${it.q_no}${it.sub_part || ""}${it.or_alt ? " (OR)" : ""}`;
  const page = tab === "q" ? it.page : it.ans && it.ans.page;
  $("pgno").textContent = page ? `Page ${page}` : "No page recorded";
  $("pageimg").src = page ? `pages/${it.paper}_p${page}.jpg` : "";
  const q = d?.edit?.text ?? it.text, at = d?.edit?.ans_text ?? it.ans?.text, mk = d?.edit?.marks ?? it.marks;
  let h = `<p><span class="tag">${it.why}</span> <span class="tag">${esc(it.qtype)}</span> <span class="tag">${mk} marks</span>
    ${d ? `<strong class="status-${d.status}"> ${d.status}</strong>` : ""}</p>
    <p class="meta">Section ${esc(it.section)} · ${esc(it.chapter)} · ${esc(it.level)}</p>`;
  if (it.flags.length) h += `<p class="flag">⚠ ${it.flags.map(esc).join("<br>⚠ ")}</p>`;
  h += `<h4>Question</h4><div class="txt" id="qt">${tex(q)}</div>`;
  if (it.options) h += `<ol type="A" class="opts">${it.options.map(o => `<li>${tex(o)}</li>`).join("")}</ol>`;
  if (it.figures.length) h += `<div class="figs">${it.figures.map(f => `<img src="${f}">`).join("")}</div>`;
  h += `<h4>Answer${it.ans && it.ans.marks != null ? ` (${it.ans.marks} marks)` : ""}</h4>`;
  if (it.ans) {
    h += `<div class="txt" id="at">${tex(at)}</div>`;
    if (it.ans.steps.length) h += `<ul>${it.ans.steps.map(s => `<li>${tex(s.text)} <span class="meta">${s.marks ?? "–"}</span></li>`).join("")}</ul>`;
    if (it.ans.figures.length) h += `<div class="figs">${it.ans.figures.map(f => `<img src="${f}">`).join("")}</div>`;
  } else h += `<p class="meta">No matching answer.</p>`;
  if (editing) h += `<h4>Edit</h4><label class="meta">Question</label><textarea id="eq">${esc(q)}</textarea>
    <label class="meta">Answer</label><textarea id="ea">${esc(at || "")}</textarea>
    <label class="meta">Marks <input id="em" value="${esc(mk)}" size="4"></label><br>
    <button id="saveedit">Save edit</button> <button id="canceledit">Cancel</button>`;
  h += `<p class="actions"><button onclick="decide('accepted')">Accept (a)</button><button onclick="decide('rejected')">Reject (x)</button><button onclick="startEdit()">Edit (e)</button></p>`;
  $("detail").innerHTML = h;
  if (editing) {
    $("saveedit").onclick = () => { decisions[it.key] = {status: "edited", edit: {text: $("eq").value, ans_text: $("ea").value, marks: $("em").value}}; editing = false; save(); next(); };
    $("canceledit").onclick = () => { editing = false; show(); };
  }
  try { renderMathInElement($("detail"), {delimiters: [{left: "$$", right: "$$", display: true}, {left: "$", right: "$", display: false}], throwOnError: false}); } catch (e) {}
  $("tq").className = tab === "q" ? "on" : ""; $("ta").className = tab === "a" ? "on" : "";
  stats();
}
function next(step = 1) {
  const vis = visible(), p = vis.indexOf(idx);
  if (p < 0) { show(); return; }
  idx = vis[Math.max(0, Math.min(vis.length - 1, p + step))]; tab = "q"; show();
}
function decide(status) { decisions[ITEMS[idx].key] = {status}; save(); editing = false; next(); }
function startEdit() { editing = true; show(); }
$("tq").onclick = () => { tab = "q"; show(); };
$("ta").onclick = () => { tab = "a"; show(); };
$("filter").onchange = show;
$("export").onclick = () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(decisions, null, 1)], {type: "application/json"}));
  a.download = "reviewed.json"; a.click();
};
document.addEventListener("keydown", e => {
  if (editing || /TEXTAREA|INPUT|SELECT/.test(e.target.tagName)) return;
  ({a: () => decide("accepted"), x: () => decide("rejected"), e: startEdit, j: () => next(1), k: () => next(-1)})[e.key]?.();
});
window.addEventListener("load", show);
</script></body></html>
"""

if __name__ == "__main__":
    main()
