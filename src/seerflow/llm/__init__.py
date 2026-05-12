"""LLM integration: explanations, NL hunting, multi-backend.

Public surface:

- ``LLMBackend`` — Protocol every backend implements (S-070).
- ``LlamaCppBackend`` — local CPU backend via ``llama-cpp-python`` (S-070).
- ``OllamaBackend`` — HTTP backend talking to a user-managed Ollama
  daemon (S-098).
- ``build_llm_backend(cfg)`` — config-driven factory with graceful absence
  (S-070, S-098).

Downstream stories (S-071 alert explanation, S-072 NL hunt, S-099 cloud,
S-100 rule suggestion) program against ``LLMBackend`` only.
"""

from __future__ import annotations

from seerflow.llm.backends.llama_cpp import LlamaCppBackend
from seerflow.llm.backends.ollama import OllamaBackend
from seerflow.llm.factory import build_llm_backend
from seerflow.llm.protocol import LLMBackend

__all__ = ["LLMBackend", "LlamaCppBackend", "OllamaBackend", "build_llm_backend"]
