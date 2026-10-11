"""Generate static HTML preview for extracted questions and crops."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

STRUCTURE_TOKEN_RE = re.compile(r"(\{\{STRUCTURE_\d+\}\})")


def render_question_html(
    question: dict,
    base_dir: Path,
) -> str:
    text = question.get("text", "")
    assets = {a["token"]: a for a in question.get("render_assets", [])}

    parts: list[str] = []
    for segment in STRUCTURE_TOKEN_RE.split(text):
        if STRUCTURE_TOKEN_RE.fullmatch(segment):
            asset = assets.get(segment)
            if asset:
                img_rel = asset["image_path"].lstrip("./")
                img_path = base_dir / img_rel
                w = asset.get("recommended_width_px", 400)
                h = asset.get("recommended_height_px", 200)
                if img_path.is_file():
                    parts.append(
                        f'<figure class="asset block">'
                        f'<img src="{html.escape(img_rel)}" width="{w}" height="{h}" alt="{html.escape(segment)}"/>'
                        f"<figcaption>{html.escape(segment)}</figcaption></figure>"
                    )
                else:
                    parts.append(
                        f'<p class="missing">Missing image for {html.escape(segment)}</p>'
                    )
            else:
                parts.append(f'<p class="missing">No asset for {html.escape(segment)}</p>')
        elif segment:
            parts.append(f"<p>{html.escape(segment).replace(chr(10), '<br/>')}</p>")

    choices = question.get("choices") or []
    choices_html = ""
    if choices:
        items = "".join(
            f"<li><strong>{html.escape(c['key'])}.</strong> {html.escape(c['text'])}</li>"
            for c in choices
        )
        choices_html = f"<ul class='choices'>{items}</ul>"

    return f"""
    <article class="question">
      <header>
        <span class="qid">Q{question.get('id')}</span>
        <span class="section">{html.escape(question.get('section', ''))}</span>
        <span class="marks">{question.get('marks', 0)} marks</span>
        <span class="type">{html.escape(question.get('type', ''))}</span>
      </header>
      <div class="body">{''.join(parts)}{choices_html}</div>
    </article>
    """


def build_preview_html(questions_path: Path, output_path: Path | None = None) -> Path:
    base_dir = questions_path.parent.resolve()
    data = json.loads(questions_path.read_text(encoding="utf-8"))
    title = html.escape(data.get("title", "Practice Test Preview"))
    questions = data.get("questions", [])
    warnings = data.get("_audit_warnings", [])

    body = "\n".join(render_question_html(q, base_dir) for q in questions)
    warn_html = ""
    if warnings:
        items = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
        warn_html = f"<ul class='warnings'>{items}</ul>"

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }}
    .question {{ border: 1px solid #ccc; border-radius: 8px; padding: 1rem; margin-bottom: 1.5rem; }}
    header {{ display: flex; gap: 1rem; flex-wrap: wrap; font-size: 0.9rem; color: #444; margin-bottom: 0.75rem; }}
    .qid {{ font-weight: bold; }}
    .asset img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
    .missing {{ color: #b00020; }}
    .warnings {{ background: #fff3cd; padding: 0.5rem 1rem; border-radius: 4px; }}
    ul.choices {{ margin-top: 0.5rem; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p>{len(questions)} questions · {data.get('total_marks', 0)} marks total</p>
  {warn_html}
  {body}
</body>
</html>
"""
    out = output_path or (base_dir / "preview.html")
    out.write_text(html_doc, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build preview.html from questions.json")
    parser.add_argument(
        "--questions",
        type=Path,
        default=Path("questions.json"),
        help="Path to questions.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output HTML path (default: beside questions.json)",
    )
    args = parser.parse_args(argv)
    if not args.questions.is_file():
        print(f"Not found: {args.questions}", file=sys.stderr)
        return 1
    path = build_preview_html(args.questions.resolve(), args.output)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
