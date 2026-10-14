# CBSE Class 12 Chemistry paper extractor

Works on digital and image-only (scanned) PDFs. Every page is sent to Gemini as an image;
the text layer is added as a hint only when it looks reliable.

## Setup
    pip install -r requirements.txt
    export GEMINI_API_KEY=...        # free key from Google AI Studio
    # optional: export GEMINI_MODEL=<model name>   (default gemini-2.5-flash)

## Run
Each PDF contains the questions followed by the answers / marking scheme at the end
(marks shown against lines or groups of lines). One PDF = one paper:
    pdfs/2024_set1.pdf
    pdfs/2023_set2.pdf

    python -m cbse_extract.run --pdf-dir ./pdfs --out ./out

## Output (./out)
- `<paper>.json`  questions with their answers and marking steps, per-page digital/image-only report, flags
- `all.jsonl`     one question per line (use this as your dataset)
- `figures/`      cropped structures/diagrams (question and answer)
- `review.md`     everything that needs a human look
- `cache/`        raw model responses; reruns are free, and a quota hit loses no progress

## Free-tier notes
- The script sleeps between calls and backs off on 429s. If the daily quota runs out, rerun the next day.
- Fix the flagged items in review.md, and keep the corrected JSON as your gold set for few-shot prompts
  or a later QLoRA fine-tune (Qwen2.5-VL on Kaggle/Colab with Unsloth).

## Verifying the dataset against the PDFs
    python -m cbse_extract.review --pdf-dir ./pdfs --out ./out [--sample 0.1]

Open `out/review/index.html`. It lists every flagged question plus a random sample (default 10%) of
the unflagged ones, with the PDF page on the left and the extracted question/answer on the right.
Keys: `a` accept, `x` reject, `e` edit, `j`/`k` next/previous. The header shows the error rate among
the sampled (unflagged) questions, which estimates how many errors the flags miss. Click
"Export decisions" to download `reviewed.json`, then merge it into a new dataset:

    python -m cbse_extract.review --apply reviewed.json --out ./out    # writes out/all.reviewed.jsonl

Questions are also flagged when most of their words are missing from the page's text layer (digital pages only).
The page loads KaTeX from cdnjs, so it needs an internet connection to render chemistry.
