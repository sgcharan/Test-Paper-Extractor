"""Find PDF files under a dataset or folder (Kaggle zips often nest subfolders)."""

from __future__ import annotations

from pathlib import Path


def _is_pdf(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".pdf"


def discover_pdfs(root: Path, recursive: bool = True) -> list[Path]:
    root = root.resolve()
    if not root.is_dir():
        return []
    iterator = root.rglob("*") if recursive else root.glob("*")
    return sorted(p for p in iterator if _is_pdf(p))


def format_tree_hint(root: Path, max_entries: int = 25) -> str:
    """Short listing to help debug wrong Kaggle dataset paths."""
    root = root.resolve()
    if not root.is_dir():
        return f"(not a directory: {root})"
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            lines.append(str(path.relative_to(root)))
        if len(lines) >= max_entries:
            lines.append("...")
            break
    return "\n  ".join(lines) if lines else "(no files under this path)"
