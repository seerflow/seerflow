"""``LLMBackend`` Protocol — single async ``complete`` surface (S-070).

Every concrete backend (``LlamaCppBackend`` in this story, ``OllamaBackend``
in S-098, ``CloudBackend`` in S-099) implements this Protocol independently —
no shared base class — so each backend can be imported in isolation without
transitively pulling in the others' optional dependencies.

Streaming completions are intentionally **out of scope** for v1; the Protocol
returns a plain ``str``. A future Protocol extension can add a ``stream(...)``
method additively without breaking existing backends.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMBackend(Protocol):
    """Pluggable LLM backend surface.

    Implementations must expose:

    - ``name`` — short identifier (used in ``/api/v1/health`` and logs).
    - ``async complete(prompt, *, max_tokens, temperature, stop)`` — single-shot
      generation. ``stop`` is a tuple of stop strings; the backend honours them
      when the underlying engine supports it, otherwise applies a best-effort
      post-trim.

    Concurrent calls are the backend's responsibility to serialise where
    required (e.g. ``llama_cpp.Llama`` is not thread-safe).
    """

    name: str

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
        stop: tuple[str, ...] = (),
    ) -> str: ...
