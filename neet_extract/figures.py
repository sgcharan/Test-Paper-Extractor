"""Place figure crops from the PDF's own geometry instead of trusting the model's bounding box.

The model estimates boxes by eye and can be several percent off on dense two-column pages (NEET 2018 Q66: the box
sat just below the reaction scheme). For PDFs with vector drawings / embedded images we snap the box to the
nearest drawing cluster; for every PDF we check the final crop (not empty, not just prose text).
"""
import fitz  # PyMuPDF

PAGE_SPAN = 0.35      # drawings longer than this share of the page are column rules / borders, not figures
GAP_X, GAP_Y = 0.035, 0.012   # clusters merge when closer than this share of page width / height
ROW_GAP_X = 0.16      # when no cluster is inside the model box, clusters on one row this close merge (reaction schemes)
ROW_MAX_H = 0.25      # ... as long as the merged row stays shorter than this share of the page height
EDGE_X = 0.05        # horizontal reach kept from the model box beside a snapped cluster
NEAR_Y = 0.12         # a cluster this close (share of page height) to the model box can replace it
INSIDE = 0.6          # share of a cluster that must lie in the model box for the box to be kept as a union
LABEL_MAX_CHARS = 14  # short text lines (OH, Na+, CHCl3 ...) next to a drawing belong to the figure
PROSE_MIN_CHARS = 25
PROSE_WORDS_FLAG = 6
PAD_X, PAD_Y = 0.012, 0.004   # final padding, share of page size (small vertically: prose lines sit just below figures)
INK_MIN = 0.004       # share of non-white pixels below which a crop counts as empty


def _is_scanned(page) -> bool:
    area = page.rect.width * page.rect.height
    return any(page.get_image_bbox(i).get_area() > 0.8 * area for i in page.get_images(full=True))


def _shapes(page):
    """(figure-like rects, x of the column divider or None)."""
    W, H = page.rect.width, page.rect.height
    rects = [d["rect"] for d in page.get_drawings()]
    rects += [page.get_image_bbox(i) for i in page.get_images(full=True)]
    out, divider = [], None
    for r in rects:
        if r.is_empty and r.width == 0 and r.height == 0:
            continue
        if r.width > PAGE_SPAN * W or r.height > PAGE_SPAN * H:
            if r.height > PAGE_SPAN * H and r.width < 8 and 0.4 * W < r.x0 < 0.6 * W:
                divider = (r.x0 + r.x1) / 2
            continue
        # bond lines are zero-width/height rects, which never "intersect" anything: give them a little body
        out.append(fitz.Rect(r.x0 - 0.5, r.y0 - 0.5, r.x1 + 0.5, r.y1 + 0.5))
    return out, divider


def _row_merge(clusters: list, W: float, H: float, divider) -> list:
    """Join clusters that sit on one row of a reaction scheme (ring -> arrow -> ring), never across the column divider."""
    cl = [fitz.Rect(c) for c in clusters]
    merged = True
    while merged:
        merged = False
        for i, a in enumerate(cl):
            for b in cl[i + 1:]:
                overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
                gap = max(a.x0, b.x0) - min(a.x1, b.x1)
                u = a | b
                crosses = divider is not None and u.x0 < divider < u.x1
                if (overlap >= 0.5 * min(a.height, b.height) and gap <= ROW_GAP_X * W
                        and u.height <= ROW_MAX_H * H and not crosses):
                    cl.remove(b)
                    cl[i] = u
                    merged = True
                    break
            if merged:
                break
    return cl


def _clusters(rects: list, W: float, H: float) -> list:
    """Union rects that lie within (GAP_X*W, GAP_Y*H) of each other."""
    clusters = []
    for r in rects:
        r = fitz.Rect(r)
        merged = True
        while merged:
            merged = False
            for c in clusters:
                grown = fitz.Rect(c.x0 - GAP_X * W, c.y0 - GAP_Y * H, c.x1 + GAP_X * W, c.y1 + GAP_Y * H)
                if grown.intersects(r):
                    r |= c
                    clusters.remove(c)
                    merged = True
                    break
        clusters.append(r)
    return clusters


def _lines(page) -> list:
    """[(rect, text)] for each text line."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = "".join(s["text"] for s in ln["spans"]).strip()
            if t:
                out.append((fitz.Rect(ln["bbox"]), t))
    return out


def _with_labels(rect, lines: list) -> fitz.Rect:
    """Grow rect to include short text lines that sit inside or right next to it (atom labels, reagents)."""
    r = fitz.Rect(rect)
    near = fitz.Rect(r.x0 - 12, r.y0 - 12, r.x1 + 12, r.y1 + 12)
    for lr, t in lines:
        if len(t) <= LABEL_MAX_CHARS and near.intersects(lr):
            r |= lr
        elif len(t) <= 40 and r.intersects(lr):  # text sharing a line with the drawing (a substituent label)
            r |= lr
    return r


def _prose_words(rect, lines: list) -> int:
    n = 0
    for lr, t in lines:
        if len(t) >= PROSE_MIN_CHARS:
            inter = lr & rect
            if not inter.is_empty and inter.get_area() > 0.5 * lr.get_area():
                n += len(t.split())
    return n


def _ink(page, rect) -> float:
    pm = page.get_pixmap(dpi=50, clip=rect, colorspace=fitz.csGRAY)
    px = pm.samples
    return sum(1 for v in px if v < 200) / max(1, len(px))


def _gap(a, b) -> float:
    dy = max(0.0, max(a.y0, b.y0) - min(a.y1, b.y1))
    dx = max(0.0, max(a.x0, b.x0) - min(a.x1, b.x1))
    return dy if dx == 0 else float("inf")  # only clusters in the same column count as near


def refine(doc, fig: dict) -> dict:
    """Return {'crop_bbox': [ymin,xmin,ymax,xmax] (0-1000), 'crop_method': str, 'flags': [str]}."""
    n = fig["page"]
    if not 1 <= n <= len(doc) or len(fig["bbox"]) != 4:
        return {"crop_bbox": fig["bbox"], "crop_method": "model", "flags": ["figure page/bbox invalid"]}
    page = doc[n - 1]
    W, H = page.rect.width, page.rect.height
    y0, x0, y1, x1 = [max(0.0, min(1000.0, float(v))) / 1000 for v in fig["bbox"]]
    box = fitz.Rect(min(x0, x1) * W, min(y0, y1) * H, max(x0, x1) * W, max(y0, y1) * H)
    flags, method, final = [], "model", box
    lines = _lines(page)

    if _is_scanned(page):
        method = "model-scanned"
    else:
        shapes, divider = _shapes(page)
        cl = _clusters(shapes, W, H)
        inside = [c for c in cl if c.get_area() > 0 and (c & box).get_area() >= INSIDE * c.get_area()]
        if inside:
            final = fitz.Rect(inside[0])
            for c in inside[1:]:
                final |= c
            method = "snapped"
        else:
            rows = _row_merge(cl, W, H, divider)
            near = sorted(((_gap(c, box), c) for c in rows if _gap(c, box) <= NEAR_Y * H), key=lambda t: t[0])
            if near:
                final, method = fitz.Rect(near[0][1]), "snapped-near"
        if method.startswith("snapped"):
            final = _with_labels(final, lines)
            if method == "snapped":  # the model's box was roughly right: keep its horizontal reach for side labels (-Cl, -OH)
                side = fitz.Rect(final.x0 - EDGE_X * W, final.y0, final.x1 + EDGE_X * W, final.y1) & box
                if not side.is_empty:
                    final |= side

    final = fitz.Rect(final.x0 - PAD_X * W, final.y0 - PAD_Y * H, final.x1 + PAD_X * W, final.y1 + PAD_Y * H) & page.rect
    if final.is_empty or final.width < 10 or final.height < 10:
        return {"crop_bbox": fig["bbox"], "crop_method": method, "flags": flags + ["figure crop empty"]}
    if _ink(page, final) < INK_MIN:
        flags.append("figure crop empty")
    if method in ("model", "model-scanned") and not _is_scanned(page) and _prose_words(final, lines) >= PROSE_WORDS_FLAG:
        flags.append("figure crop looks like text only")
    bbox = [round(final.y0 / H * 1000), round(final.x0 / W * 1000), round(final.y1 / H * 1000), round(final.x1 / W * 1000)]
    return {"crop_bbox": bbox, "crop_method": method, "flags": flags}
