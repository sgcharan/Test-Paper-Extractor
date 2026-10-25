"""Pydantic schemas (also used as Gemini response_schema) for NEET 'Answers & Solutions' booklets.
Every NEET question is a 4-option MCQ with the answer and worked solution printed right after it."""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# NCERT Class 11 + 12 chemistry chapters as covered by NEET.
CHAPTERS = {
    "chemistry": [
        "Some Basic Concepts of Chemistry",
        "Structure of Atom",
        "Classification of Elements and Periodicity",
        "Chemical Bonding and Molecular Structure",
        "States of Matter",
        "Thermodynamics",
        "Equilibrium",
        "Redox Reactions",
        "Hydrogen",
        "s-Block Elements",
        "p-Block Elements (Group 13 and 14)",
        "Organic Chemistry: Basic Principles and Techniques",
        "Hydrocarbons",
        "Environmental Chemistry",
        "Solid State",
        "Solutions",
        "Electrochemistry",
        "Chemical Kinetics",
        "Surface Chemistry",
        "General Principles of Isolation of Elements",
        "p-Block Elements (Group 15 to 18)",
        "d- and f-Block Elements",
        "Coordination Compounds",
        "Haloalkanes and Haloarenes",
        "Alcohols, Phenols and Ethers",
        "Aldehydes, Ketones and Carboxylic Acids",
        "Amines",
        "Biomolecules",
        "Polymers",
        "Chemistry in Everyday Life",
        "Practical Chemistry (Salt Analysis, Titrations)",
        "Other / Unknown",
    ],
}
UNKNOWN_CHAPTER = "Other / Unknown"
CHEMISTRY_CHAPTERS = CHAPTERS["chemistry"]
Chapter = Enum("Chapter", {c: c for c in CHEMISTRY_CHAPTERS}, type=str)


class Figure(BaseModel):
    page: int = Field(description="1-indexed page number in the PDF")
    bbox: list[int] = Field(description="[ymin, xmin, ymax, xmax] normalised to 0-1000 on that page")
    kind: str = Field(description="structure | reaction | diagram | graph | table")
    where: str = Field(description="question | option | solution")


class NeetQuestion(BaseModel):
    q_no: int = Field(description="Question number as printed (e.g. 46); NEET booklets do not restart per subject")
    question_text: str = Field(description="Full question stem incl. statement lists / match-the-list tables. "
                                           "Chemistry in \\ce{...} / LaTeX.")
    options: list[str] = Field(description="Exactly 4 options in printed order, without their (1)-(4) / (a)-(d) labels")
    subject: str = Field(description="Subject this question belongs to: chemistry | physics | biology")
    correct_option: Optional[int] = Field(description="The single printed answer as 1-4 (a=1, b=2, c=3, d=4); "
                                                      "null if the key is Bonus, lists several options, or is not printed")
    accepted_options: list[int] = Field(default_factory=list,
                                        description="All options the key accepts when it lists more than one, e.g. "
                                                    "'(3 or 4)' -> [3, 4], '(1 & 4)' -> [1, 4]; otherwise []")
    answer_note: Optional[str] = Field(default=None, description="The printed key verbatim when it is not a single "
                                                                 "option, e.g. 'Bonus', '3 or 4'; otherwise null")
    solution_text: str = Field(description="The printed solution / explanation after the answer, in full")
    chapter: Chapter
    page: int = Field(description="Page where the question number is printed")
    figures: list[Figure] = Field(default_factory=list)


class NeetChunk(BaseModel):
    """What one model call returns: the questions found on a window of pages."""
    exam_year: Optional[str] = None
    paper_code: Optional[str] = None
    questions: list[NeetQuestion]
