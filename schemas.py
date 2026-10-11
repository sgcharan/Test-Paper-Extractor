"""Pydantic models for VLM chemistry paper extraction."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class StructureRef(BaseModel):
    structure_id: str = Field(
        description="Local ID on this page, e.g. S1, S2, matching placeholders in question text."
    )
    bbox_norm: List[float] = Field(
        description="Bounding box [x1, y1, x2, y2] in 0-1000 coordinates relative to page image."
    )
    caption: Optional[str] = Field(
        default=None,
        description="Short label for the diagram, e.g. 'Reaction scheme for question 14'.",
    )


class Choice(BaseModel):
    key: str = Field(description="Option letter (e.g., A, B, C, D)")
    text: str = Field(description="Content of the option.")


class QuestionDraft(BaseModel):
    section: str = Field(description="e.g., Section A, Section C")
    marks: int = Field(ge=0)
    type: str = Field(
        description="MCQ, Numerical, Organic Mechanism, Assertion-Reason, or Case-based"
    )
    text_with_placeholders: str = Field(
        description=(
            "Question text with {{STRUCTURE_<local_id>}} tokens where diagrams belong."
        )
    )
    structure_ids: List[str] = Field(
        default_factory=list,
        description="Local structure IDs referenced in text_with_placeholders.",
    )
    choices: Optional[List[Choice]] = None
    solution: Optional[str] = Field(
        default=None,
        description="Step-by-step solution if visible on this page.",
    )
    continued_from_previous: bool = Field(
        default=False,
        description="True if this question continues from the previous page.",
    )


class PageExtraction(BaseModel):
    page_index: int = Field(ge=0)
    questions: List[QuestionDraft] = Field(default_factory=list)
    structures: List[StructureRef] = Field(default_factory=list)


class RenderAsset(BaseModel):
    token: str = Field(description="Placeholder token, e.g. {{STRUCTURE_1}}")
    image_path: str = Field(description="Relative path to crop PNG, e.g. ./crops/q14_structure.png")
    display_type: Literal["block", "inline"] = "block"
    recommended_width_px: int = Field(ge=1)
    recommended_height_px: int = Field(ge=1)
    source_page: Optional[int] = Field(
        default=None, description="0-based page index in source PDF."
    )
    bbox_px: Optional[List[int]] = Field(
        default=None, description="Crop box [x1, y1, x2, y2] in page pixels."
    )


class Question(BaseModel):
    id: int
    section: str
    marks: int
    type: str
    text: str = Field(description="Final text with global {{STRUCTURE_N}} tokens.")
    choices: Optional[List[Choice]] = None
    solution: Optional[str] = None
    render_assets: List[RenderAsset] = Field(default_factory=list)


class PracticeTest(BaseModel):
    title: str
    total_marks: int
    questions: List[Question]


class PageCheckpoint(BaseModel):
    """Serialized state after each processed page."""

    pdf_path: str
    out_dir: str
    dpi: int
    last_completed_page: int = Field(
        description="0-based index of last successfully processed page."
    )
    page_extractions: List[PageExtraction] = Field(default_factory=list)
    global_structure_counter: int = 0
