"""Pydantic schemas (also used as Gemini response_schema) and constants."""
import os
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")  # change if a newer free model exists

# Rationalised syllabus plus chapters found in older (pre-2023) papers.
CHAPTERS = [
    "Solid State",
    "Solutions",
    "Electrochemistry",
    "Chemical Kinetics",
    "d- and f-Block Elements",
    "Surface Chemistry",
    "General Principles of Isolation of Elements",
    "p-Block Elements",
    "Coordination Compounds",
    "Haloalkanes and Haloarenes",
    "Alcohols, Phenols and Ethers",
    "Aldehydes, Ketones and Carboxylic Acids",
    "Amines",
    "Biomolecules",
    "Polymers",
    "Chemistry in Everyday Life",
    "Other / Unknown",
]
COGNITIVE = [
    "Remembering/Understanding",
    "Applying",
    "Analysing/Evaluating/Creating",
]

Chapter = Enum("Chapter", {c: c for c in CHAPTERS}, type=str)
Cognitive = Enum("Cognitive", {c: c for c in COGNITIVE}, type=str)


class MarkStyle(str, Enum):
    per_step = "per_step"  # marks split across lines/steps of the answer
    whole = "whole"        # marks given for the answer as a whole


class Figure(BaseModel):
    page: int = Field(description="1-indexed page number in the PDF")
    bbox: list[int] = Field(description="[ymin, xmin, ymax, xmax] normalised to 0-1000 on that page")
    kind: str = Field(description="structure | reaction | diagram | graph | table")


class QuestionItem(BaseModel):
    q_no: str = Field(description="Question number as printed, e.g. '21'")
    sub_part: Optional[str] = Field(default=None, description="'a', 'b', 'i' ... or null")
    or_alt: int = Field(default=0, description="0 = main question, 1 = the 'OR' alternative")
    section: str = Field(description="A, B, C, D or E")
    marks: float
    qtype: str = Field(description="mcq | assertion_reason | very_short | short | long | case_based | value_based")
    question_text: str = Field(description="Full question in English. Chemistry in \\ce{...} / LaTeX.")
    question_text_alt: Optional[str] = Field(default=None, description="Same question in the other language, if printed")
    alt_language: Optional[str] = None
    options: Optional[list[str]] = Field(default=None, description="MCQ options, in order")
    is_case_based: bool = False
    chapter: Chapter
    cognitive_level: Cognitive
    page: int
    figures: list[Figure] = Field(default_factory=list)


class Step(BaseModel):
    text: str
    marks: Optional[float] = None


class MarkingItem(BaseModel):
    q_no: str
    sub_part: Optional[str] = None
    or_alt: int = 0
    marks_total: Optional[float] = None
    style: MarkStyle
    answer_text: str = Field(description="Full answer; chemistry in \\ce{...} / LaTeX")
    steps: list[Step] = Field(default_factory=list, description="Only if marks are given per line/step")
    page: int
    figures: list[Figure] = Field(default_factory=list)


class Paper(BaseModel):
    """One PDF: questions first, then the answers / marking scheme at the end."""
    exam_year: Optional[str] = None
    paper_code: Optional[str] = None
    total_marks: Optional[float] = None
    questions: list[QuestionItem]
    answers: list[MarkingItem]
