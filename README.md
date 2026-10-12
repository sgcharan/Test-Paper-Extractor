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
