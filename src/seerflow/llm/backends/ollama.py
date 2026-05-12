"""Ollama LLM backend (S-098).

Talks to a user-managed Ollama daemon over HTTP. Implements the same
``LLMBackend`` Protocol that ``LlamaCppBackend`` satisfies, so downstream
consumers (alert explanation S-071, NL hunt S-072, future S-100) can be
retargeted to GPU-served inference by flipping ``llm.backend: ollama`` in
config — no application code change.

Design constraints (see story S-098 design rationale for the full why):

- **Per-call** ``aiohttp.ClientSession``. Long-lived sessions hold dead
  sockets across daemon restarts and require lifecycle plumbing.
- **No retries inside the backend.** Consumers (S-071, S-072) carry their
  own request-level deadline; stacking exponential-backoff would silently
  blow past it or require budget propagation.
- **No startup probe.** Health reflects *configuration* readiness, not
  *runtime* daemon health (same posture as TAXII feeds).
- **Typed exception** ``OllamaBackendError`` (``RuntimeError`` subclass)
  mirrors ``seerflow.utils.http.GetWithRetryError`` so generic
  ``except Exception`` consumers continue to work.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from seerflow.utils.http import _scrub

_log = logging.getLogger(__name__)


# Defensive ceiling — the largest ``max_tokens`` the backend will ever honour,
# regardless of caller request. Matches ``LLAMA_CPP_MAX_TOKENS_HARD_CAP`` so a
# prompt template tuned against one backend behaves identically on the other.
OLLAMA_MAX_TOKENS_HARD_CAP = 1024

# Cap the body snippet included in HTTP-error messages. Long bodies clutter
# logs and can include sensitive payloads (e.g. echoed prompts).
_BODY_SNIPPET_MAX = 200


class OllamaBackendError(RuntimeError):
    """Raised when an Ollama call cannot produce a valid completion.

    Wraps three failure classes:

    1. Transport errors (``aiohttp.ClientError``, ``TimeoutError``, ``OSError``)
       — daemon down, DNS failure, GPU OOM mid-request.
    2. Non-2xx HTTP status — model not pulled, malformed request, etc. The
       message includes a ``≤200``-char body snippet.
    3. Malformed payload — non-JSON body, missing ``response`` key, or
       non-string ``response`` value.

    The exception subclasses ``RuntimeError`` so generic ``except Exception``
    consumers (S-071's explanation endpoint, S-072's hunt endpoint) keep
    working unchanged.
    """


class OllamaBackend:
    """``LLMBackend`` implementation that POSTs to ``/api/generate``.

    Stateless from a connection standpoint: each ``complete(...)`` call opens
    and closes its own ``aiohttp.ClientSession``. The cost is ``O(1 ms)``
    against a localhost daemon — well within the noise of LLM inference
    latency.
    """

    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_s: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = float(timeout_s)

    @property
    def _generate_url(self) -> str:
        return f"{self.base_url}/api/generate"

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
        stop: tuple[str, ...] = (),
    ) -> str:
        """Single-shot completion. One HTTP POST, no retries."""
        capped = min(int(max_tokens), OLLAMA_MAX_TOKENS_HARD_CAP)
        options: dict[str, Any] = {
            "num_predict": capped,
            "temperature": float(temperature),
        }
        if stop:
            options["stop"] = list(stop)
        body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        url = self._generate_url
        t0 = time.monotonic()
        payload = await self._post_once(url, body)
        latency_ms = (time.monotonic() - t0) * 1000.0
        text = self._extract_text(payload, prompt, url)
        _log.debug(
            "ollama: complete model=%s tokens=%d latency_ms=%.1f",
            self.model,
            capped,
            latency_ms,
        )
        return text

    async def _post_once(self, url: str, body: dict[str, Any]) -> Any:
        """Open a per-call session, POST once, return parsed JSON payload."""
        timeout = aiohttp.ClientTimeout(total=self.timeout_s)
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.post(url, json=body) as resp,
            ):
                return await self._read_payload(resp, url)
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            raise OllamaBackendError(
                f"ollama: request to {url} failed: {_scrub(repr(exc))}"
            ) from exc

    async def _read_payload(self, resp: aiohttp.ClientResponse, url: str) -> Any:
        """Read + parse the response, raising ``OllamaBackendError`` on issues."""
        if resp.status >= 400:
            snippet = await self._read_snippet(resp)
            raise OllamaBackendError(f"ollama: HTTP {resp.status} from {url}: {_scrub(snippet)}")
        try:
            return await resp.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError) as exc:
            snippet = await self._read_snippet(resp)
            raise OllamaBackendError(
                f"ollama: malformed response from {url}: not JSON ({_scrub(snippet)!r})"
            ) from exc

    @staticmethod
    async def _read_snippet(resp: aiohttp.ClientResponse) -> str:
        try:
            text = await resp.text()
        except Exception:  # pragma: no cover - defensive: aiohttp may also fail here
            return ""
        return text[:_BODY_SNIPPET_MAX]

    @staticmethod
    def _extract_text(payload: Any, prompt: str, url: str) -> str:
        """Pull the ``response`` field out of the payload, normalising the prefix."""
        if not isinstance(payload, dict) or "response" not in payload:
            raise OllamaBackendError(
                f"ollama: malformed response from {url}: missing 'response' field"
            )
        text = payload["response"]
        if not isinstance(text, str):
            raise OllamaBackendError(
                f"ollama: malformed response from {url}: 'response' is "
                f"{type(text).__name__}, expected str"
            )
        if text.startswith(prompt):
            text = text[len(prompt) :]
        return text
