from .schemas import CHEMISTRY_CHAPTERS

PROMPT_VERSION = "neet-v2"  # part of the prompt text, so editing it invalidates the extraction cache


FIRST_WINDOW_RULE = """
  EXCEPTION (these pages only): if a page starts with the tail of a question (e.g. the end of its stem, then options)
  and the question's number and first lines are NOT printed anywhere on the page before it (the source file cut them
  off), still output that question with q_no = the previous question's number + 1 and start question_text with
  '[STEM START MISSING] '. The same applies to a question tail at the very top of the first page."""


def chunk_prompt(subject: str, first_page: int, last_page: int) -> str:
    chapters = CHEMISTRY_CHAPTERS
    first_window_rule = FIRST_WINDOW_RULE if first_page == 1 else ""
    return f"""[{PROMPT_VERSION}]
You are extracting data from a NEET (UG) {subject.title()} 'Answers & Solutions' booklet. Each page is given as an
image (source of truth), sometimes with a text layer that may be garbled for chemistry. Pages {first_page}-{last_page}
of the PDF are provided; the page numbers in the '=== PAGE n ===' markers are the real PDF page numbers.

Every question is a 4-option multiple-choice question, followed immediately by its printed answer
('Answer (3)', 'Answer Key: (3)', 'Ans. [3]') and a worked solution ('Sol.', 'Solution:'). Question numbers are
the printed ones and do not start at 1 (a Chemistry file typically holds Q46-90 or Q51-100).

Rules:
- Output one record per question whose NUMBER is printed on these pages, in order. If a page starts with the
  tail of a question whose number is on the previous page (not provided), skip that tail.{first_window_rule}
- Pages may be two-column: read each column top to bottom, left column first.
- The file may start or end with questions of another subject (a shared page); still output them but set `subject`
  correctly (chemistry | physics | biology) for every question.
- A question that starts near the bottom of the last page and continues beyond it: still output what is visible.
- question_text: the full stem, including statement lists (A, B, C ... / I, II ...), Assertion-Reason statements and
  'Match List I with List II' tables (write a table as lines 'A - III', or a Markdown table). Do not include the options.
- options: exactly 4, in printed order, without their (1)-(4) or (a)-(d) labels. Copy them exactly.
- correct_option: the answer the booklet prints, as 1-4 (letters a-d = 1-4). Do NOT solve the question yourself.
  If the key lists several options ('(3 or 4)', '(1 & 4)', 'Solution: (2,3)') set correct_option = null,
  accepted_options = those options, answer_note = the printed key. If the key is 'Bonus' set correct_option = null,
  accepted_options = [], answer_note = 'Bonus'. If nothing is printed, all three stay empty/null.
- solution_text: the printed solution in full (text and equations); never invent or shorten. If the solution is only a
  figure, write '[FIGURE]'.
- Write chemical formulas and equations in mhchem LaTeX: \\ce{{H2SO4}}, \\ce{{SO4^{{2-}}}}, \\ce{{A + B -> C}}, \\ce{{<=>}}.
  Write maths/units in LaTeX too (e.g. $k = 2.3 \\times 10^{{-3}}\\ s^{{-1}}$).
- Do NOT try to transcribe structural formulas, reaction schemes drawn as pictures, graphs or circuit-like diagrams.
  Instead add a Figure entry (page number, tight bounding box [ymin, xmin, ymax, xmax] normalised to 0-1000, kind,
  and where = question | option | solution) and write '[FIGURE]' at that place in the text (for an option that is a
  picture, make the option text '[FIGURE]').
- Ignore running headers/footers (e.g. 'NEET (UG) - 2018 (Code-AA)', page numbers, coaching-institute logos).
- chapter: choose exactly one of {chapters}.
- Fill exam_year and paper_code (booklet/test code) from the cover or header if visible, else null.
- Copy numbers and question numbers exactly as printed. If text is illegible write [ILLEGIBLE]; never invent content.
"""
