from .schemas import CHAPTERS

COMMON = r"""
You are extracting data from a CBSE Class 12 Chemistry document. Each page is given as an image
(source of truth), sometimes with a text layer that may be garbled for chemistry.

Rules:
- Write chemical formulas and equations in mhchem LaTeX: \ce{H2SO4}, \ce{SO4^{2-}}, \ce{A + B -> C}, \ce{<=>}.
  Write maths/units in LaTeX too (e.g. $k = 2.3 \times 10^{-3}\ s^{-1}$).
- Do NOT try to transcribe structural diagrams. Instead add a Figure entry with the page number and a
  tight bounding box [ymin, xmin, ymax, xmax] normalised to 0-1000, and write "[FIGURE]" at that place in the text.
- Papers may be bilingual (English + Hindi/other). Extract ENGLISH ONLY: completely ignore the Hindi/other-language
  text and never output it. Never create two records for one question.
- 'OR' alternatives: same q_no, or_alt = 1. Parts joined by 'OR' are alternatives, not sub-parts.
- Sub-parts: split ONLY when the question paper itself prints labelled sub-parts ((a)/(b), (i)/(ii)/(iii)).
  Then output one record per printed label, with sub_part set to that label ('a','b','i','ii'), repeating any
  shared stem or passage at the start of each question_text; marks = that part's own marks (the parts must add
  up to the question's total). Use ONE level only: the outermost printed label. Labels nested inside a part,
  e.g. (a) containing (i)(ii)(iii), stay inside that part's question_text and answer; never output 'a(i)'.
  Exception - choice questions ("Attempt any five of the following", "(Any three)"): output ONE record with
  sub_part = null, all parts inside question_text, marks = the question's total, and ONE answer listing every part. If a question has no printed labels, output ONE record with sub_part = null,
  even if its answer lists marks per line or it has several sentences or clauses. If the marking scheme gives
  one combined block for a question with labelled sub-parts, still output one answer per sub-part.
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
- marks: marks for that question (or sub-part if marked separately). qtype: mcq | assertion_reason | very_short | short | long | case_based | value_based (the 'value based question' with a social/ethical context).
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
