"""Local CPU LLM backend powered by ``llama-cpp-python`` (S-070).

The wheel is an **optional** dependency. ``import seerflow.llm.backends.llama_cpp``
must always succeed — the actual ``llama_cpp`` import is deferred until the
backend is constructed AND first asked to ``complete(...)`` (lazy load),
so a system without the wheel can still import the package.

Concurrent ``complete`` calls are serialised through an ``asyncio.Lock`` —
``llama_cpp.Llama`` is not thread-safe for concurrent inference on a single
instance (KV-cache corruption otherwise).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# Defensive ceiling — the largest ``max_tokens`` the backend will ever honour,
# regardless of caller request. Phi-4-mini's typical alert-explanation budget
# is ~300 tokens; 1024 sits comfortably above any sensible consumer demand and
# well below the model's 4 k context window.
LLAMA_CPP_MAX_TOKENS_HARD_CAP = 1024


def _resolve_n_threads(n_threads: int | None) -> int:
    """Return the effective ``n_threads`` value.

    ``None`` resolves to ``max(1, (os.cpu_count() or 1) - 1)`` so the receiver
    event loop keeps one core. ``os.cpu_count()`` may return ``None`` on
    exotic containers — the ``or 1`` guard handles that.
    """
    if n_threads is not None:
        return n_threads
    return max(1, (os.cpu_count() or 1) - 1)


class LlamaCppBackend:
    """``LLMBackend`` implementation backed by a local GGUF model.

    The underlying ``llama_cpp.Llama`` instance is constructed lazily on the
    first ``complete(...)`` call. This keeps import cheap and lets the factory
    decide whether to keep the backend without paying for model load.
    """

    name = "llama_cpp"

    def __init__(
        self,
        model_path: Path | str,
        *,
        n_ctx: int = 4096,
        n_threads: int | None = None,
        n_gpu_layers: int = 0,
        seed: int = 42,
        logits_all: bool = False,
        verbose: bool = False,
    ) -> None:
        self.model_path = Path(model_path)
        self.n_ctx = int(n_ctx)
        self.n_threads = _resolve_n_threads(n_threads)
        self.n_gpu_layers = int(n_gpu_layers)
        self.seed = int(seed)
        self.logits_all = bool(logits_all)
        self.verbose = bool(verbose)
        self._llm: Any = None
        self._lock = asyncio.Lock()

    def _ensure_loaded(self) -> Any:
        """Load the underlying ``llama_cpp.Llama`` exactly once."""
        if self._llm is not None:
            return self._llm
        # Lazy import — never at module top level. ``ImportError`` here is
        # the factory's responsibility to catch; by the time we reach this
        # method, the factory has already decided the backend should exist.
        import llama_cpp  # type: ignore[import-not-found]

        self._llm = llama_cpp.Llama(
            model_path=str(self.model_path),
            n_ctx=self.n_ctx,
            n_threads=self.n_threads,
            n_gpu_layers=self.n_gpu_layers,
            seed=self.seed,
            logits_all=self.logits_all,
            verbose=self.verbose,
        )
        _log.info(
            "llama_cpp: model_loaded path=%s n_ctx=%d n_threads=%d mmap=True",
            self.model_path,
            self.n_ctx,
            self.n_threads,
        )
        return self._llm

    @staticmethod
    def _extract_text(payload: Any, prompt: str) -> str:
        """Pull the completion text out of a ``create_completion`` payload.

        Some GGUF quants return ``prompt + completion``; others return just
        the completion. We normalise to "just the completion" by stripping
        the prompt prefix if present.
        """
        if isinstance(payload, dict):
            choices = payload.get("choices") or []
            text = choices[0].get("text", "") if choices and isinstance(choices[0], dict) else ""
        else:
            text = ""
        if isinstance(text, str) and text.startswith(prompt):
            text = text[len(prompt) :]
        return text if isinstance(text, str) else ""

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
        stop: tuple[str, ...] = (),
    ) -> str:
        """Single-shot completion. Serialised; offloaded to a worker thread."""
        capped = min(int(max_tokens), LLAMA_CPP_MAX_TOKENS_HARD_CAP)
        # Serialise — ``llama_cpp.Llama`` is not safe for concurrent calls
        # on a single instance.
        async with self._lock:
            llm = self._ensure_loaded()

            def _run() -> Any:
                return llm.create_completion(
                    prompt,
                    max_tokens=capped,
                    temperature=temperature,
                    stop=list(stop),
                )

            t0 = time.monotonic()
            payload = await asyncio.to_thread(_run)
            latency_ms = (time.monotonic() - t0) * 1000.0
        text = self._extract_text(payload, prompt)
        _log.debug("llama_cpp: complete tokens=%d latency_ms=%.1f", capped, latency_ms)
        return text
