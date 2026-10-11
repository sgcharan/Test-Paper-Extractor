"""Local Ollama vision backend."""

from __future__ import annotations

import base64
import json
import re
from io import BytesIO
from typing import TYPE_CHECKING, Optional

from ollama import Client

from vlm_backends.base import VisionBackend

from schemas import PageExtraction
from vlm_backends.prompts import RETRY_FIX_JSON_PROMPT, build_page_prompt

if TYPE_CHECKING:
    from PIL import Image


def _encode_image_jpeg_base64(image: Image.Image) -> str:
    buffered = BytesIO()
    rgb = image.convert("RGB")
    rgb.save(buffered, format="JPEG", quality=92)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def _parse_json_content(raw: str) -> dict:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


class OllamaVisionBackend(VisionBackend):
    def __init__(
        self,
        model: str = "qwen2.5vl:latest",
        host: Optional[str] = None,
        temperature: float = 0.1,
    ) -> None:
        self.model = model
        self.client = Client(host=host) if host else Client()
        self.temperature = temperature

    def _chat(self, prompt: str, image: Image.Image) -> str:
        image_bytes = _encode_image_jpeg_base64(image)
        response = self.client.chat(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_bytes],
                }
            ],
            options={"temperature": self.temperature},
        )
        return response["message"]["content"]

    def extract_page(self, page_image: Image.Image, page_index: int) -> PageExtraction:
        prompt = build_page_prompt(page_index)
        raw = self._chat(prompt, page_image)
        try:
            data = _parse_json_content(raw)
            return PageExtraction.model_validate(data)
        except (json.JSONDecodeError, ValueError) as first_err:
            fix_prompt = RETRY_FIX_JSON_PROMPT.format(page_index=page_index)
            fix_prompt += f"\n\nPrevious output:\n{raw[:8000]}"
            raw2 = self._chat(fix_prompt, page_image)
            try:
                data = _parse_json_content(raw2)
                return PageExtraction.model_validate(data)
            except (json.JSONDecodeError, ValueError) as second_err:
                raise RuntimeError(
                    f"Ollama returned invalid JSON for page {page_index}: {first_err}; retry: {second_err}"
                ) from second_err
