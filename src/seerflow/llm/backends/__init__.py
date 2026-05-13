"""LLM backend implementations (S-070, S-098, S-099).

Each backend is in its own module so its optional dependencies (e.g.
``llama-cpp-python``, ``anthropic``, ``openai``) only load when the
backend itself is imported. The cloud module is safe to import even when
its SDKs are absent — ``ImportError`` is deferred to the constructor.
"""

from __future__ import annotations

from seerflow.llm.backends.cloud import (
    AnthropicBackend,
    CloudBackendError,
    OpenAIBackend,
)
from seerflow.llm.backends.llama_cpp import LlamaCppBackend
from seerflow.llm.backends.ollama import OllamaBackend, OllamaBackendError

__all__ = [
    "AnthropicBackend",
    "CloudBackendError",
    "LlamaCppBackend",
    "OllamaBackend",
    "OllamaBackendError",
    "OpenAIBackend",
]
