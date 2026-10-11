"""Prompts and JSON schema hints for page extraction."""

import json

from schemas import PageExtraction

PAGE_EXTRACTION_PROMPT = """You are a meticulous CBSE Class 12 Chemistry evaluator. Analyze the provided image of a chemistry question paper page.

Rules:
- Extract every real exam question on this page. Do NOT emit section headers, page numbers, or instructions unless they are part of a question.
- Pay close attention to chemical structures, mechanisms, benzene rings, skeletal formulas, reaction arrows, and electrochemical diagrams.
- For questions that depend on a diagram, keep the literal question wording and insert placeholders exactly as {{STRUCTURE_<local_id>}} where the figure belongs (e.g. {{STRUCTURE_S1}}). Use short local IDs like S1, S2, S3.
- Set structure_ids on each question to list every local structure ID referenced in text_with_placeholders.
- For each distinct diagram on the page (structures, schemes, cells), add an entry in structures with structure_id matching the placeholders, and bbox_norm as [x1, y1, x2, y2] in 0-1000 coordinates relative to this page image (top-left origin).
- If a question clearly continues from the previous page, set continued_from_previous to true and only include the continuation text.
- marks: use the marks printed for the question, or 0 if unknown.
- type: one of MCQ, Numerical, Organic Mechanism, Assertion-Reason, Case-based, or Short Answer.

Respond with ONLY valid JSON matching this structure (no markdown fences):
{schema_example}

Set page_index to {page_index}.
"""


def build_page_prompt(page_index: int) -> str:
    example = PageExtraction(
        page_index=page_index,
        questions=[
            {
                "section": "Section C",
                "marks": 3,
                "type": "Organic Mechanism",
                "text_with_placeholders": "Identify the major product in:\\n\\n{{STRUCTURE_S1}}\\n\\nGive IUPAC name.",
                "structure_ids": ["S1"],
                "choices": None,
                "solution": None,
                "continued_from_previous": False,
            }
        ],
        structures=[
            {
                "structure_id": "S1",
                "bbox_norm": [100, 200, 900, 550],
                "caption": "Reaction sequence",
            }
        ],
    )
    return PAGE_EXTRACTION_PROMPT.format(
        schema_example=json.dumps(example.model_dump(), indent=2),
        page_index=page_index,
    )


RETRY_FIX_JSON_PROMPT = """Your previous response was not valid JSON or did not match the required schema.
Return ONLY corrected JSON with the same semantic content. No markdown, no explanation.
Required page_index: {page_index}
"""
