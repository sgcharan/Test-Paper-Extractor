"""Gemini free-tier wrapper: structured output, disk cache, backoff on rate limits."""
import hashlib
import json
import time
from pathlib import Path

from google import genai
from google.genai import types

from .schemas import MODEL

PROMPT_VERSION = "v2"  # bump to invalidate the cache after editing prompts
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client()  # reads GEMINI_API_KEY from env
    return _client


def extract(pdf_path: Path, parts: list, prompt: str, schema, cache_dir: Path, min_interval: float = 6.0):
    key = hashlib.sha256(
        pdf_path.read_bytes() + prompt.encode() + MODEL.encode() + PROMPT_VERSION.encode()
    ).hexdigest()[:24]
    cache_file = cache_dir / f"{key}.json"
    if cache_file.exists():
        return schema.model_validate_json(cache_file.read_text())

    cache_dir.mkdir(parents=True, exist_ok=True)
    for attempt in range(6):
        try:
            resp = _get_client().models.generate_content(
                model=MODEL,
                contents=[prompt, *parts],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.0,
                ),
            )
            result = resp.parsed if resp.parsed is not None else schema.model_validate_json(resp.text)
            cache_file.write_text(result.model_dump_json(indent=1))
            time.sleep(min_interval)  # stay under free-tier requests/minute
            return result
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if any(s in msg for s in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")):
                wait = 5 * 2 ** attempt
                print(f"  rate-limited/unavailable, sleeping {wait}s ...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Gemini retries exhausted (daily quota may be used up; rerun tomorrow - cache keeps progress)")
