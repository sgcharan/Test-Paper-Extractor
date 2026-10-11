"""CLI: vision-first extraction of chemistry PDFs to structured JSON + crops."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from PIL import Image

from image_utils import count_pdf_pages, render_pdf_page
from merge_utils import audit_question_tokens, merge_checkpoint_to_practice_test
from schemas import PageCheckpoint, PageExtraction
from vlm_backends.base import VisionBackend
from vlm_backends import get_backend

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CHECKPOINT_NAME = "checkpoint.json"
QUESTIONS_NAME = "questions.json"


def slugify_pdf_name(pdf_path: Path) -> str:
    return re.sub(r"[^\w\-]+", "_", pdf_path.stem).strip("_") or "paper"


def load_checkpoint(path: Path) -> PageCheckpoint | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return PageCheckpoint.model_validate(data)


def save_checkpoint(path: Path, checkpoint: PageCheckpoint) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        checkpoint.model_dump_json(indent=2),
        encoding="utf-8",
    )


def qwen_backend_kwargs_from_args(args: argparse.Namespace) -> dict:
    return {
        "model_id": args.qwen_model,
        "load_in_4bit": not args.no_4bit,
        "max_vlm_side": args.max_vlm_side,
        "max_new_tokens": args.max_new_tokens,
    }


def process_pdf(
    pdf_path: Path,
    out_dir: Path,
    dpi: int,
    start_page: int,
    backend_name: str,
    poppler_path: str | None,
    title: str | None,
    backend_kwargs: dict,
    save_page_images: bool,
    backend: VisionBackend | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    crops_dir = out_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = out_dir / CHECKPOINT_NAME

    checkpoint = load_checkpoint(path=checkpoint_path)
    if checkpoint is None:
        checkpoint = PageCheckpoint(
            pdf_path=str(pdf_path.resolve()),
            out_dir=str(out_dir.resolve()),
            dpi=dpi,
            last_completed_page=-1,
            page_extractions=[],
            global_structure_counter=0,
        )
    elif checkpoint.pdf_path != str(pdf_path.resolve()):
        logger.warning("Checkpoint PDF path differs; starting fresh checkpoint.")
        checkpoint = PageCheckpoint(
            pdf_path=str(pdf_path.resolve()),
            out_dir=str(out_dir.resolve()),
            dpi=dpi,
            last_completed_page=-1,
            page_extractions=[],
            global_structure_counter=0,
        )

    total_pages = count_pdf_pages(str(pdf_path), poppler_path=poppler_path)
    if start_page > 0:
        checkpoint.last_completed_page = max(checkpoint.last_completed_page, start_page - 1)

    page_images: dict[int, Image.Image] = {}
    already_done = len(checkpoint.page_extractions) >= total_pages

    if already_done:
        logger.info("Checkpoint has all %s pages; rebuilding questions.json only.", total_pages)
    elif backend is None:
        backend = get_backend(backend_name, **backend_kwargs)

    for page_index in range(checkpoint.last_completed_page + 1, total_pages):
        if already_done:
            break
        logger.info("Processing page %s/%s", page_index + 1, total_pages)
        page_image = render_pdf_page(
            str(pdf_path),
            page_index,
            dpi=dpi,
            poppler_path=poppler_path,
        )
        page_images[page_index] = page_image

        if save_page_images:
            pages_dir = out_dir / "pages"
            pages_dir.mkdir(parents=True, exist_ok=True)
            page_image.save(pages_dir / f"page_{page_index + 1:03d}.jpg", quality=92)

        try:
            extraction: PageExtraction = backend.extract_page(page_image, page_index)
        except Exception as exc:
            logger.error("Failed page %s: %s", page_index + 1, exc)
            save_checkpoint(checkpoint_path, checkpoint)
            raise

        extraction.page_index = page_index
        checkpoint.page_extractions.append(extraction)
        checkpoint.last_completed_page = page_index
        save_checkpoint(checkpoint_path, checkpoint)
        # Drop full-page bitmap from RAM during long papers (re-render for merge if needed).
        page_images.pop(page_index, None)

    for page_index in range(len(checkpoint.page_extractions)):
        if page_index not in page_images:
            page_images[page_index] = render_pdf_page(
                str(pdf_path),
                page_index,
                dpi=dpi,
                poppler_path=poppler_path,
            )

    paper_title = title or f"CBSE Class 12 Chemistry — {pdf_path.stem}"
    practice_test = merge_checkpoint_to_practice_test(
        checkpoint,
        page_images,
        crops_dir,
        title=paper_title,
    )

    audit_errors = audit_question_tokens(practice_test.questions)
    for err in audit_errors:
        logger.warning("Token audit: %s", err)

    out_json = out_dir / QUESTIONS_NAME
    payload = practice_test.model_dump(mode="json")
    if audit_errors:
        payload["_audit_warnings"] = audit_errors
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(
        "Wrote %s questions to %s",
        len(practice_test.questions),
        out_json,
    )
    return out_json


def add_extraction_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dpi", type=int, default=300, help="Render DPI (default: 300)")
    parser.add_argument(
        "--start-page",
        type=int,
        default=0,
        help="0-based page to start/resume from",
    )
    parser.add_argument(
        "--backend",
        choices=("ollama", "qwen_hf"),
        default="ollama",
        help="VLM backend (default: ollama)",
    )
    parser.add_argument(
        "--poppler-path",
        type=str,
        default=None,
        help="Poppler bin path (Windows)",
    )
    parser.add_argument("--title", type=str, default=None, help="Practice test title")
    parser.add_argument(
        "--ollama-model",
        type=str,
        default="qwen2.5vl:latest",
        help="Ollama model tag",
    )
    parser.add_argument(
        "--ollama-host",
        type=str,
        default=None,
        help="Ollama host URL",
    )
    parser.add_argument(
        "--qwen-model",
        type=str,
        default="Qwen/Qwen2.5-VL-3B-Instruct",
        help="Hugging Face model id for qwen_hf backend",
    )
    parser.add_argument(
        "--no-4bit",
        action="store_true",
        help="Disable 4-bit quantization for qwen_hf",
    )
    parser.add_argument(
        "--max-vlm-side",
        type=int,
        default=1280,
        help="Longest image side sent to VLM (default: 1280; lowers GPU memory)",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=2048,
        help="Max tokens generated per page (default: 2048)",
    )
    parser.add_argument(
        "--save-page-images",
        action="store_true",
        help="Save rendered page JPEGs under out-dir/pages/",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract chemistry exam PDFs using a vision-language model.",
    )
    parser.add_argument("--pdf", required=True, type=Path, help="Input PDF path")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: ./out/<pdf_slug>)",
    )
    add_extraction_arguments(parser)
    return parser


def build_extraction_only_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    add_extraction_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    pdf_path = args.pdf.resolve()
    if not pdf_path.is_file():
        logger.error("PDF not found: %s", pdf_path)
        return 1

    out_dir = args.out_dir
    if out_dir is None:
        out_dir = Path("out") / slugify_pdf_name(pdf_path)
    else:
        out_dir = out_dir.resolve()

    backend_kwargs: dict = {}
    if args.backend == "ollama":
        backend_kwargs = {
            "model": args.ollama_model,
            "host": args.ollama_host,
        }
    else:
        backend_kwargs = qwen_backend_kwargs_from_args(args)

    try:
        process_pdf(
            pdf_path=pdf_path,
            out_dir=out_dir,
            dpi=args.dpi,
            start_page=args.start_page,
            backend_name=args.backend,
            poppler_path=args.poppler_path,
            title=args.title,
            backend_kwargs=backend_kwargs,
            save_page_images=args.save_page_images,
        )
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
