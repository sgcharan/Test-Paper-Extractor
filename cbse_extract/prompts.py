from .schemas import CHAPTERS

COMMON = r"""
You are extracting data from a CBSE Class 12 Chemistry document. Each page is given as an image
(source of truth), sometimes with a text layer that may be garbled for chemistry.

Rules:
- Write chemical formulas and equations in mhchem LaTeX: \ce{H2SO4}, \ce{SO4^{2-}}, \ce{A + B -> C}, \ce{<=>}.
  Write maths/units in LaTeX too (e.g. $k = 2.3 \times 10^{-3}\ s^{-1}$).
- Do NOT try to transcribe structural diagrams. Instead add a Figure entry with the page number and a
  tight bounding box [ymin, xmin, ymax, xmax] normalised to 0-1000, and write "[FIGURE]" at that place in the text.
- Papers may be bilingual (English + Hindi/other). Put English in the main text field and the other
  language in the *_alt field of the SAME record. Never create two records for one question.
- 'OR' alternatives: same q_no, or_alt = 1. Sub-parts: sub_part = 'a','b','i','ii'.
- Copy numbers, marks and question numbers exactly as printed. Never invent content; if illegible, write [ILLEGIBLE].
- Include every question/answer in the document, in order.
"""

PAPER_PROMPT = COMMON + f"""
Each document contains a QUESTION PAPER first, followed by its ANSWERS / MARKING SCHEME (usually at the
end, after the questions). Extract both into ONE response:
- `questions`: every question from the question-paper part.
- `answers`: the answer for every question from the answer / marking-scheme part.
Match them by using the same q_no / sub_part / or_alt in both lists. The answer part may be in a
different order or format; use the question number printed there.

QUESTIONS
- section: the section letter (A-E) the question falls under, from the section headers.
- marks: marks for that question (or sub-part if marked separately). qtype: mcq | assertion_reason | very_short | short | long | case_based.
- For case-based questions: repeat the case passage at the start of question_text of each sub-question, set is_case_based = true.
- For MCQs fill `options` in order.
- chapter: choose exactly one of {CHAPTERS}.
- cognitive_level: CBSE competency level of the question:
  * Remembering/Understanding - recall of a fact, definition, name reaction, statement; explaining a concept.
  * Applying - numericals, predicting products, using a formula or rule in a new situation.
  * Analysing/Evaluating/Creating - reasoning 'why', comparing, interpreting data, multi-step inference, case-based inference.
- Also fill exam_year, paper_code, total_marks from the header if present.

ANSWERS
- Marks are printed against individual lines or groups of lines of a short/long answer (e.g. 1/2, 1, 1/2 + 1/2).
  Then set style = per_step and list each line or group of lines, in order, as one entry in `steps`
  (text + its marks). Marks like 1/2 must be 0.5.
- If marks are given only for the whole answer, set style = whole, steps = [].
- Always also fill answer_text with the complete answer and marks_total with the total marks.
- For MCQs the answer_text is the correct option letter and its text.
- Ignore general instructions and examiner notes that are not answers.
"""
