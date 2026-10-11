"""Vision-language model backends for page extraction."""

from vlm_backends.base import VisionBackend
from vlm_backends.ollama_backend import OllamaVisionBackend

__all__ = ["VisionBackend", "OllamaVisionBackend"]


def get_backend(name: str, **kwargs) -> VisionBackend:
    if name == "ollama":
        return OllamaVisionBackend(**kwargs)
    if name == "qwen_hf":
        from vlm_backends.qwen_hf_backend import QwenHFVisionBackend

        return QwenHFVisionBackend(**kwargs)
    raise ValueError(f"Unknown backend: {name}. Use 'ollama' or 'qwen_hf'.")
