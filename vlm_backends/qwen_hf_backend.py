"""Hugging Face Qwen2.5-VL backend for Kaggle GPU."""

from __future__ import annotations

import gc
import json
import logging
import re
from typing import TYPE_CHECKING

import torch
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

from image_utils import resize_for_vlm
from schemas import PageExtraction
from vlm_backends.base import VisionBackend
from vlm_backends.prompts import RETRY_FIX_JSON_PROMPT, build_page_prompt

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

try:
    from qwen_vl_utils import process_vision_info
except ImportError:

    def process_vision_info(messages):  # type: ignore
        image_inputs = []
        video_inputs = []
        for message in messages:
            for item in message.get("content", []):
                if item.get("type") == "image":
                    image_inputs.append(item["image"])
                elif item.get("type") == "video":
                    video_inputs.append(item["video"])
        return image_inputs, video_inputs


def _parse_json_content(raw: str) -> dict:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def _release_cuda_memory() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


class QwenHFVisionBackend(VisionBackend):
    def __init__(
        self,
        model_id: str = "Qwen/Qwen2.5-VL-3B-Instruct",
        load_in_4bit: bool = True,
        temperature: float = 0.1,
        max_new_tokens: int = 2048,
        max_vlm_side: int = 1280,
    ) -> None:
        self.model_id = model_id
        self.temperature = temperature
        self.max_new_tokens = max_new_tokens
        self.max_vlm_side = max_vlm_side

        quantization_config = None
        model_kwargs: dict = {
            "trust_remote_code": True,
            "device_map": "auto",
            "low_cpu_mem_usage": True,
        }
        if load_in_4bit:
            from transformers import BitsAndBytesConfig

            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
            model_kwargs["quantization_config"] = quantization_config
        else:
            model_kwargs["torch_dtype"] = (
                torch.float16 if torch.cuda.is_available() else torch.float32
            )

        self.processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        try:
            self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                model_id,
                attn_implementation="sdpa",
                **model_kwargs,
            )
        except TypeError:
            self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                model_id,
                **model_kwargs,
            )
        self.model.eval()
        logger.info(
            "Loaded %s (4bit=%s, max_vlm_side=%s)",
            model_id,
            load_in_4bit,
            max_vlm_side,
        )

    def _generate(self, prompt: str, page_image: Image.Image) -> str:
        vlm_image = resize_for_vlm(page_image, max_side=self.max_vlm_side)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": vlm_image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
        inputs = inputs.to(self.model.device)

        try:
            with torch.inference_mode():
                generated_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens,
                    temperature=self.temperature if self.temperature > 0 else None,
                    do_sample=self.temperature > 0,
                )
            trimmed = [
                out_ids[len(in_ids) :]
                for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            return self.processor.batch_decode(
                trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]
        finally:
            del inputs
            _release_cuda_memory()

    def extract_page(self, page_image: Image.Image, page_index: int) -> PageExtraction:
        prompt = build_page_prompt(page_index)
        raw = self._generate(prompt, page_image)
        try:
            data = _parse_json_content(raw)
            return PageExtraction.model_validate(data)
        except (json.JSONDecodeError, ValueError) as first_err:
            fix_prompt = RETRY_FIX_JSON_PROMPT.format(page_index=page_index)
            fix_prompt += f"\n\nPrevious output:\n{raw[:8000]}"
            raw2 = self._generate(fix_prompt, page_image)
            try:
                data = _parse_json_content(raw2)
                return PageExtraction.model_validate(data)
            except (json.JSONDecodeError, ValueError) as second_err:
                raise RuntimeError(
                    f"Qwen HF returned invalid JSON for page {page_index}: {first_err}; retry: {second_err}"
                ) from second_err
