"""Gemini wrapper: structured output, disk cache, backoff on rate limits, per-call token usage."""
import hashlib
import json
import time
from pathlib import Path

from google import genai
from google.genai import types

from .schemas import MODEL

PROMPT_VERSION = "v4"  # bump to invalidate the cache after editing prompts
RETRYABLE_CODES = (429, 500, 503, 504)
# transport-level failures (DNS drop, reset, timeout) carry no HTTP code: retry them too
NETWORK_ERRORS = ("ConnectError", "RemoteProtocolError", "ReadError", "ReadTimeout", "ConnectTimeout",
                  "WriteError", "PoolTimeout", "ServerDisconnectedError", "ConnectionError", "TimeoutError")
_client = None


class EmptyResponseError(RuntimeError):
    """The model returned no text at all (token limit hit while thinking, safety block, ...)."""


class RecitationBlocked(RuntimeError):
    """Gemini's recitation filter blocked the output. Retrying (any temperature, any Flash model) does not
    help, so the paper is skipped and remembered in the cache folder instead of being retried."""


class FatalAPIError(RuntimeError):
    """Retrying cannot help (bad key, no credits, retired model, quota exhausted): stop the batch."""


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client()  # reads GEMINI_API_KEY from env
    return _client


def _usage_dict(resp) -> dict:
    u = getattr(resp, "usage_metadata", None)
    g = lambda name: getattr(u, name, None) or 0  # noqa: E731
    return {
        "model": MODEL,
        "prompt_tokens": g("prompt_token_count"),
        "output_tokens": g("candidates_token_count"),
        "thinking_tokens": g("thoughts_token_count"),
        "total_tokens": g("total_token_count"),
        "cached": False,
    }


def extract(pdf_path: Path, parts: list, prompt: str, schema, cache_dir: Path, min_interval: float = 6.0):
    """Return (parsed_result, usage_dict). On a cache hit, usage is read from the sidecar file
    written when the call was first made (zeros if it predates usage logging)."""
    key = hashlib.sha256(
        pdf_path.read_bytes() + prompt.encode() + MODEL.encode() + PROMPT_VERSION.encode()
    ).hexdigest()[:24]
    cache_file = cache_dir / f"{key}.json"
    usage_file = cache_dir / f"{key}.usage.json"
    if cache_file.exists():
        try:
            result = schema.model_validate_json(cache_file.read_text(encoding="utf-8"))
            try:
                usage = json.loads(usage_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                usage = {"model": MODEL, "prompt_tokens": 0, "output_tokens": 0,
                         "thinking_tokens": 0, "total_tokens": 0}
            return result, {**usage, "cached": True}
        except ValueError:
            print(f"  ignoring corrupt cache file {cache_file.name}, re-fetching")

    cache_dir.mkdir(parents=True, exist_ok=True)
    skip_file = cache_dir / f"{key}.skipped.json"
    if skip_file.exists():
        raise RecitationBlocked(json.loads(skip_file.read_text(encoding="utf-8")).get("reason", "RECITATION"))
    empty = 0
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
            if resp.parsed is None and not resp.text:
                cand = resp.candidates[0] if getattr(resp, "candidates", None) else None
                if "RECITATION" in str(getattr(cand, "finish_reason", "")):
                    reason = f"RECITATION block on {MODEL} (usage={_usage_dict(resp)})"
                    skip_file.write_text(json.dumps({"reason": reason}), encoding="utf-8")
                    raise RecitationBlocked(reason)
                raise EmptyResponseError(
                    f"empty response (finish_reason={getattr(cand, 'finish_reason', None)}, "
                    f"prompt_feedback={getattr(resp, 'prompt_feedback', None)}, usage={_usage_dict(resp)})")
            result = resp.parsed if resp.parsed is not None else schema.model_validate_json(resp.text)
            usage = _usage_dict(resp)
            cache_file.write_text(result.model_dump_json(indent=1), encoding="utf-8")
            usage_file.write_text(json.dumps(usage), encoding="utf-8")
            time.sleep(min_interval)  # stay under free-tier requests/minute
            return result, usage
        except Exception as e:  # noqa: BLE001
            if isinstance(e, RecitationBlocked):
                raise
            if isinstance(e, EmptyResponseError):
                empty += 1
                if empty >= 3:
                    raise  # per-PDF failure with the diagnostic; the batch continues
                print(f"  {e}; retrying ({empty}/2)")
                time.sleep(5)
                continue
            code = getattr(e, "code", None)
            retryable = code in RETRYABLE_CODES if code is not None else (
                type(e).__name__ in NETWORK_ERRORS or any(s in str(e) for s in ("429", "503", "UNAVAILABLE")))
            if code == 429 and "PerDay" in str(e):  # daily quota: backoff cannot help, stop the batch now
                raise FatalAPIError(f"Gemini daily quota exhausted for {MODEL} (resets within 24h; "
                                    f"cache keeps progress): {str(e)[:300]}") from e
            if retryable:
                wait = 5 * 2 ** attempt
                print(f"  rate-limited/unavailable ({code}), sleeping {wait}s ...")
                time.sleep(wait)
            elif code in (401, 402, 403, 404):  # 400 can be specific to one PDF, so it stays per-paper
                raise FatalAPIError(f"Gemini API error {code}: {str(e)[:300]}") from e
            else:
                raise
    raise FatalAPIError("Gemini retries exhausted (daily quota may be used up; rerun tomorrow - cache keeps progress)")
