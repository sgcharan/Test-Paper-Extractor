"""Batch-process multiple PDFs and write a manifest."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from extract_paper import build_extraction_only_parser, process_pdf, slugify_pdf_name
from vlm_backends import get_backend

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
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
        help="Glob pattern within pdf_dir",
    )
    known, remaining = parser.parse_known_args(argv)

    single_parser = build_extraction_only_parser()
    single_args = single_parser.parse_args(remaining)

    pdf_dir = known.pdf_dir.resolve()
    if not pdf_dir.is_dir():
        logger.error("Not a directory: %s", pdf_dir)
        return 1

    pdfs = sorted(pdf_dir.glob(known.glob))
    if not pdfs:
        logger.error("No PDFs matching %s in %s", known.glob, pdf_dir)
        return 1

    shared_backend = None
    if single_args.backend == "qwen_hf":
        logger.info("Loading Qwen HF model once for batch...")
        shared_backend = get_backend(
            "qwen_hf",
            model_id=single_args.qwen_model,
            load_in_4bit=not single_args.no_4bit,
        )

    manifest_entries = []
    for pdf_path in pdfs:
        out_dir = known.out_root / slugify_pdf_name(pdf_path)
        logger.info("=== %s -> %s ===", pdf_path.name, out_dir)
        backend_kwargs: dict = {}
        if single_args.backend == "ollama":
            backend_kwargs = {
                "model": single_args.ollama_model,
                "host": single_args.ollama_host,
            }
        else:
            backend_kwargs = {
                "model_id": single_args.qwen_model,
                "load_in_4bit": not single_args.no_4bit,
            }

        try:
            json_path = process_pdf(
                pdf_path=pdf_path.resolve(),
                out_dir=out_dir.resolve(),
                dpi=single_args.dpi,
                start_page=single_args.start_page,
                backend_name=single_args.backend,
                poppler_path=single_args.poppler_path,
                title=single_args.title,
                backend_kwargs=backend_kwargs,
                save_page_images=single_args.save_page_images,
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

    manifest_path = known.out_root / "manifest.json"
    known.out_root.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest_entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Manifest written to %s", manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
