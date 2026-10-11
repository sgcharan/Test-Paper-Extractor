"""Merge page extractions into final practice test with global structure tokens."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image

from image_utils import crop_structure, save_crop
from schemas import (
    PageCheckpoint,
    PracticeTest,
    Question,
    QuestionDraft,
    RenderAsset,
    StructureRef,
)

STRUCTURE_TOKEN_RE = re.compile(r"\{\{STRUCTURE_[^}]+\}\}")


def audit_question_tokens(questions: List[Question]) -> List[str]:
    """Return list of validation error messages."""
    errors: List[str] = []
    for q in questions:
        tokens_in_text = set(STRUCTURE_TOKEN_RE.findall(q.text))
        tokens_in_assets = {a.token for a in q.render_assets}
        missing_assets = tokens_in_text - tokens_in_assets
        extra_assets = tokens_in_assets - tokens_in_text
        if missing_assets:
            errors.append(
                f"Question {q.id}: text references {missing_assets} without render_assets"
            )
        if extra_assets:
            errors.append(
                f"Question {q.id}: render_assets {extra_assets} not referenced in text"
            )
    return errors


def _local_placeholder(structure_id: str) -> str:
    return f"{{{{STRUCTURE_{structure_id}}}}}"


def merge_checkpoint_to_practice_test(
    checkpoint: PageCheckpoint,
    page_images: Dict[int, Image.Image],
    crops_dir: Path,
    title: str,
) -> PracticeTest:
    """
    Build final questions from checkpoint, saving crops and assigning global tokens.
    page_images: map page_index -> PIL Image (needed for cropping).
    """
    global_counter = checkpoint.global_structure_counter
    questions_out: List[Question] = []
    question_id = 0

    # Per-page maps: local structure_id -> global token string
    for page in checkpoint.page_extractions:
        local_to_global: Dict[str, str] = {}
        local_to_asset: Dict[str, Tuple[str, StructureRef, int]] = {}

        page_img = page_images.get(page.page_index)
        structure_by_id = {s.structure_id: s for s in page.structures}

        for draft in page.questions:
            for sid in draft.structure_ids:
                if sid in local_to_global:
                    continue
                if sid not in structure_by_id:
                    continue
                global_counter += 1
                token = f"{{{{STRUCTURE_{global_counter}}}}}"
                local_to_global[sid] = token
                local_to_asset[sid] = (token, structure_by_id[sid], global_counter)

        for draft in page.questions:
            if draft.continued_from_previous and questions_out:
                prev = questions_out[-1]
                extra_text = _replace_local_placeholders(
                    draft.text_with_placeholders, local_to_global
                )
                prev.text = prev.text.rstrip() + "\n\n" + extra_text.lstrip()
                _attach_assets_for_draft(
                    prev,
                    draft,
                    local_to_global,
                    local_to_asset,
                    page.page_index,
                    page_img,
                    crops_dir,
                )
                prev.marks = max(prev.marks, draft.marks)
                continue

            question_id += 1
            text = _replace_local_placeholders(
                draft.text_with_placeholders, local_to_global
            )
            q = Question(
                id=question_id,
                section=draft.section,
                marks=draft.marks,
                type=draft.type,
                text=text,
                choices=draft.choices,
                solution=draft.solution,
                render_assets=[],
            )
            _attach_assets_for_draft(
                q,
                draft,
                local_to_global,
                local_to_asset,
                page.page_index,
                page_img,
                crops_dir,
            )
            questions_out.append(q)

    checkpoint.global_structure_counter = global_counter
    total_marks = sum(q.marks for q in questions_out)
    return PracticeTest(title=title, total_marks=total_marks, questions=questions_out)


def _replace_local_placeholders(text: str, local_to_global: Dict[str, str]) -> str:
    out = text
    for local_id, global_token in local_to_global.items():
        out = out.replace(_local_placeholder(local_id), global_token)
    return out


def _attach_assets_for_draft(
    question: Question,
    draft: QuestionDraft,
    local_to_global: Dict[str, str],
    local_to_asset: Dict[str, Tuple[str, StructureRef, int]],
    page_index: int,
    page_img: Image.Image | None,
    crops_dir: Path,
) -> None:
    existing_tokens = {a.token for a in question.render_assets}
    for sid in draft.structure_ids:
        if sid not in local_to_global:
            continue
        token = local_to_global[sid]
        if token in existing_tokens:
            continue
        _, structure_ref, global_num = local_to_asset[sid]
        rel_name = f"./crops/q{question.id}_structure_{global_num}.png"
        crop_path = crops_dir / f"q{question.id}_structure_{global_num}.png"

        bbox_px = None
        width_px, height_px = 400, 200
        if page_img is not None:
            crop, bbox_px_list = crop_structure(page_img, structure_ref)
            save_crop(crop, crop_path)
            width_px, height_px = crop.size
            bbox_px = list(bbox_px_list)

        asset = RenderAsset(
            token=token,
            image_path=rel_name,
            display_type="block",
            recommended_width_px=width_px,
            recommended_height_px=height_px,
            source_page=page_index,
            bbox_px=bbox_px,
        )
        question.render_assets.append(asset)
        existing_tokens.add(token)
