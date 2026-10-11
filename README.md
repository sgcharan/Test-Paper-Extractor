# Test Paper Extractor (VLM-first)

Vision-only pipeline for CBSE-style chemistry PDFs: render pages at high DPI, extract questions with a multimodal model, crop diagrams, and emit JSON with `{{STRUCTURE_N}}` placeholders and `render_assets` metadata.

## Requirements

- **Poppler** (for `pdf2image`)
  - **Kaggle**: `apt-get install -y poppler-utils` (see notebook)
  - **Windows**: [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases) — pass `--poppler-path "C:\path\to\poppler\Library\bin"`
- **Local smoke test**: [Ollama](https://ollama.com) with a vision model, e.g. `ollama pull qwen2.5vl`
- **Kaggle (primary)**: GPU + `requirements.txt` (Qwen2.5-VL via Hugging Face)

## Install

```bash
cd "Test Paper Extractor"
pip install -r requirements-local.txt   # Windows + Ollama only
# pip install -r requirements.txt       # Full install including Qwen HF
```

## Single PDF (local Ollama)

```bash
python extract_paper.py --pdf path/to/paper.pdf --backend ollama --ollama-model qwen2.5vl:latest --poppler-path "C:\path\to\poppler\Library\bin"
```

Outputs under `out/<paper_slug>/`:

- `questions.json`
- `crops/*.png`
- `checkpoint.json` (resume after interruption)
- optional `pages/` with `--save-page-images`

Resume from page 5 (0-based):

```bash
python extract_paper.py --pdf paper.pdf --start-page 5 --out-dir out/paper_slug
```

Preview:

```bash
python preview.py --questions out/paper_slug/questions.json
```

## Batch

```bash
python batch_extract.py path/to/pdf_folder --out-root out --backend qwen_hf -- --dpi 300
```

(Place backend flags after `--` when using `batch_extract.py`.)

## Kaggle

**PDFs** = Kaggle dataset. **Code** = public GitHub repo (cloned in the notebook).

### 1. Put the code on GitHub

Push this folder to a **public** repository, for example:

`https://github.com/YOUR_USERNAME/test-paper-extractor`

### 2. Upload PDFs as a Kaggle dataset

Zip your `.pdf` files so they sit at the **root** of the zip (not inside a nested folder only). Create a new Kaggle dataset from that zip, e.g. slug `chemistry-papers`.

### 3. Run the notebook on Kaggle

1. **New Notebook** → turn on **GPU** and **Internet**.
2. **Add data** → select your PDF dataset only.
3. **File → Import notebook** → choose [`kaggle/chemistry_extractor.ipynb`](kaggle/chemistry_extractor.ipynb) from this project.
4. Edit two variables in the config cell:
   - `GITHUB_REPO` → your public clone URL
   - `PDF_INPUT_DIR` → `/kaggle/input/<your-pdf-dataset-slug>` (see “Datasets mounted” printout)
5. **Run all** → download **`out.zip`** from the Output panel.

To update extraction logic later, `git push` to GitHub and re-run the notebook (it clones fresh each time).

## Output shape

Each question can reference cropped figures:

```json
{
  "id": 14,
  "section": "C",
  "marks": 3,
  "text": "Identify the major product ...\n\n{{STRUCTURE_1}}\n\n...",
  "render_assets": [
    {
      "token": "{{STRUCTURE_1}}",
      "image_path": "./crops/q14_structure_1.png",
      "display_type": "block",
      "recommended_width_px": 450,
      "recommended_height_px": 200
    }
  ]
}
```
