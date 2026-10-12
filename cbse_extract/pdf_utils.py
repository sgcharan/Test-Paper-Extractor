"""Handles digital and image-only PDFs uniformly: always send page images,
add the text layer as a hint only when it looks trustworthy."""
from pathlib import Path

import fitz  # PyMuPDF
from google.genai import types

SEND_DPI = 150   # what the model sees (balance of token cost vs. legibility)
CROP_DPI = 300   # what figure crops are saved at
SAFE_PUNCT = set(".,;:()[]{}+-=/%'\"?<>\u2192\u21cc\u00b0")


def text_is_reliable(text: str) -> bool:
    t = text.strip()
    if len(t) < 200:  # scanned page, or almost no text
        return False
    ok = sum(1 for c in t if c.isalnum() or c.isspace() or c in SAFE_PUNCT or "\u0900" <= c <= "\u097f")
    return ok / len(t) > 0.9


def english_only(text: str, max_nonascii: float = 0.2) -> str:
    """Drop lines that are not English. Hindi in these PDFs is legacy-font text that extracts as
    Latin-1 garbage (e.g. 'ŸÖß¾ÖÎŸÖÖ ÃÖê Ûú¸êüÝÖÖ'), so detect it by its share of non-ASCII characters."""
    keep = []
    for line in text.splitlines():
        s = line.strip()
        if s:
            bad = sum(1 for c in s if ord(c) > 127 and c not in SAFE_PUNCT)
            if bad / len(s) > max_nonascii:
                continue
        keep.append(line)
    return "\n".join(keep)


def build_parts(pdf_path: Path):
    """Return (gemini_parts, per_page_report)."""
    doc = fitz.open(pdf_path)
    parts, report = [], []
    for i, page in enumerate(doc, start=1):
        text = english_only(page.get_text("text"))
        digital = text_is_reliable(text)
        report.append({"page": i, "mode": "digital" if digital else "image-only"})
        img = page.get_pixmap(dpi=SEND_DPI).tobytes("jpeg", jpg_quality=85)
        parts.append(f"=== PAGE {i} ===")
        parts.append(types.Part.from_bytes(data=img, mime_type="image/jpeg"))
        if digital:
            parts.append(
                f"[TEXT LAYER PAGE {i} - may garble subscripts, charges, arrows and Hindi; "
                f"the image is the source of truth]\n{text}"
            )
    return parts, report


def crop_figure(pdf_path: Path, page_no: int, bbox, out_path: Path, pad: float = 0.01) -> bool:
    """bbox = [ymin, xmin, ymax, xmax] in 0-1000 normalised coords."""
    doc = fitz.open(pdf_path)
    if not (1 <= page_no <= len(doc)) or len(bbox) != 4:
        return False
    page = doc[page_no - 1]
    w, h = page.rect.width, page.rect.height
    ymin, xmin, ymax, xmax = [max(0.0, min(1000.0, float(v))) / 1000 for v in bbox]
    ymin, ymax = sorted((ymin, ymax))  # the model occasionally returns min/max swapped
    xmin, xmax = sorted((xmin, xmax))
    rect = fitz.Rect((xmin - pad) * w, (ymin - pad) * h, (xmax + pad) * w, (ymax + pad) * h) & page.rect
    if rect.is_empty or rect.width < 10 or rect.height < 10:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.get_pixmap(dpi=CROP_DPI, clip=rect).save(out_path)
    return True
