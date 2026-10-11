"""Batch-process multiple PDFs and write a manifest."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from extract_paper import (
    add_extraction_arguments,
    process_pdf,
    qwen_backend_kwargs_from_args,
    slugify_pdf_name,
)
from pdf_discovery import discover_pdfs, format_tree_hint
from vlm_backends import get_backend

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def build_batch_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch extract chemistry PDFs.")
    parser.add_argument(
        "pdf_dir",
        type=Path,
        help="Directory containing PDF files",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("out"),
        help="Root output directory",
    )
    parser.add_argument(
        "--glob",
        type=str,
        default="*.pdf",
        help="Glob pattern within pdf_dir (non-recursive mode only)",
    )
    parser.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Search subfolders for PDFs (default: true; typical for Kaggle datasets)",
    )
    add_extraction_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_batch_parser().parse_args(argv)

    pdf_dir = args.pdf_dir.resolve()
    if not pdf_dir.is_dir():
        logger.error("Not a directory: %s", pdf_dir)
        return 1

    if args.recursive:
        pdfs = discover_pdfs(pdf_dir, recursive=True)
    else:
        pdfs = sorted(pdf_dir.glob(args.glob))
    if not pdfs:
        logger.error(
            "No PDFs in %s (recursive=%s). Contents sample:\n  %s",
            pdf_dir,
            args.recursive,
            format_tree_hint(pdf_dir),
        )
        return 1
    logger.info("Found %s PDF(s) under %s", len(pdfs), pdf_dir)

    shared_backend = None
    if args.backend == "qwen_hf":
        logger.info("Loading Qwen HF model once for batch...")
        shared_backend = get_backend("qwen_hf", **qwen_backend_kwargs_from_args(args))

    manifest_entries = []
    for pdf_path in pdfs:
        out_dir = args.out_root / slugify_pdf_name(pdf_path)
        logger.info("=== %s -> %s ===", pdf_path.name, out_dir)
        backend_kwargs: dict = {}
        if args.backend == "ollama":
            backend_kwargs = {
                "model": args.ollama_model,
                "host": args.ollama_host,
            }
        else:
            backend_kwargs = qwen_backend_kwargs_from_args(args)

        try:
            json_path = process_pdf(
                pdf_path=pdf_path.resolve(),
                out_dir=out_dir.resolve(),
                dpi=args.dpi,
                start_page=args.start_page,
                backend_name=args.backend,
                poppler_path=args.poppler_path,
                title=args.title,
                backend_kwargs=backend_kwargs,
                save_page_images=args.save_page_images,
                backend=shared_backend,
            )
            data = json.loads(json_path.read_text(encoding="utf-8"))
            manifest_entries.append(
                {
                    "pdf": str(pdf_path),
                    "out_dir": str(out_dir),
                    "questions_json": str(json_path),
                    "question_count": len(data.get("questions", [])),
                    "total_marks": data.get("total_marks"),
                    "status": "ok",
                }
            )
        except Exception as exc:
            logger.error("Failed %s: %s", pdf_path.name, exc)
            manifest_entries.append(
                {
                    "pdf": str(pdf_path),
                    "out_dir": str(out_dir),
                    "status": "error",
                    "error": str(exc),
                }
            )

    manifest_path = args.out_root / "manifest.json"
    args.out_root.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest_entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Manifest written to %s", manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
