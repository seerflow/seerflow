"""Cloud LLM backends — Anthropic + OpenAI SDKs (S-099).

Two concrete ``LLMBackend`` implementations behind one shared
``CloudBackendError``. Each backend talks to its provider's official Python
SDK; the factory (``seerflow.llm.factory._maybe_load_cloud``) constructs the
right one based on ``llm.cloud_provider``.

Design constraints (see story S-099 design rationale for the full why):

- **Lazy SDK import** inside the constructor — ``import
  seerflow.llm.backends.cloud`` always succeeds even when the optional
  ``llm-cloud`` extra is not installed (matches ``LlamaCppBackend``).
  ``ImportError`` is re-raised from the constructor; the factory catches it
  and degrades gracefully with the install hint
  ``pip install seerflow[llm-cloud]``.
- **No retries inside the backend.** Both SDKs ship a default retry policy
  (2 attempts on 429/5xx). Layering another retry on top would silently
  blow past the consumer's deadline (S-071 / S-072 enforce ``timeout_s``
  via ``asyncio.wait_for``).
- **No startup probe.** Same posture as ``OllamaBackend`` — health reflects
  *configuration* readiness, not *runtime* daemon health.
- **Typed exception** ``CloudBackendError(RuntimeError)`` mirrors
  ``OllamaBackendError`` so generic ``except Exception`` consumers continue
  to work unchanged. The ``_scrub`` helper from
  ``seerflow.llm.backends.ollama`` redacts ``Bearer``, ``Basic``, and
  ``user:pass@`` blobs before any exception message hits the log stream.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from seerflow.llm.backends.ollama import _scrub

_log = logging.getLogger(__name__)


# Defensive ceiling — the largest ``max_tokens`` the backend will ever honour,
# regardless of caller request. Matches ``LLAMA_CPP_MAX_TOKENS_HARD_CAP`` and
# ``OLLAMA_MAX_TOKENS_HARD_CAP`` so a prompt template tuned against one
# backend continues to behave the same on any other.
CLOUD_MAX_TOKENS_HARD_CAP = 1024

# Cap the body snippet included in HTTP-error messages. Long bodies clutter
# logs and can include sensitive payloads (e.g. echoed prompts).
_BODY_SNIPPET_MAX = 200


class CloudBackendError(RuntimeError):
    """Raised when a cloud LLM call cannot produce a valid completion.

    Wraps three failure classes:

    1. Transport errors (``APIConnectionError``, ``TimeoutError``, ``OSError``)
       — DNS failure, TLS, mid-flight socket reset.
    2. Non-2xx HTTP status (``APIStatusError``) — auth failure, model not
       found, rate-limit exhausted after SDK-internal retries. The message
       includes a ``≤200``-char body snippet.
    3. Malformed payload — empty content array, non-text first block
       (Anthropic), ``None`` ``message.content`` or empty ``choices``
       (OpenAI).

    The exception subclasses ``RuntimeError`` so generic ``except Exception``
    consumers (S-071's explanation endpoint, S-072's hunt endpoint) keep
    working unchanged.
    """


def _stringify_body(body: Any) -> str:
    """Render an SDK error ``body`` field into a bounded snippet for the message."""
    if body is None:
        return ""
    if isinstance(body, str):
        return body[:_BODY_SNIPPET_MAX]
    if isinstance(body, dict):
        # Anthropic / OpenAI both nest the human-readable string at
        # ``body["error"]["message"]``. Fall back to the dict's ``str()``.
        err = body.get("error")
        if isinstance(err, dict):
            msg = err.get("message")
            if isinstance(msg, str):
                return msg[:_BODY_SNIPPET_MAX]
        return str(body)[:_BODY_SNIPPET_MAX]
    return str(body)[:_BODY_SNIPPET_MAX]


def _provider_endpoint_url(provider: str, base_url: str | None) -> str:
    """Return a stable URL string for inclusion in error messages.

    The SDK clients do not expose the configured ``base_url`` after the
    fact, so we reconstruct a best-effort string for diagnostics. Empty
    ``base_url`` resolves to the provider's documented default.
    """
    if base_url:
        return base_url.rstrip("/")
    if provider == "anthropic":
        return "https://api.anthropic.com"
    if provider == "openai":
        return "https://api.openai.com/v1"
    return f"<{provider}>"


class AnthropicBackend:
    """``LLMBackend`` talking to Anthropic Claude via ``anthropic.AsyncAnthropic``.

    Concurrent calls are safe — the SDK client is documented as
    concurrent-safe.
    """

    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_s: float = 30.0,
        base_url: str | None = None,
    ) -> None:
        # Lazy import — ``ImportError`` here is the factory's responsibility
        # to catch. ``import seerflow.llm.backends.cloud`` always succeeds.
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised via sys.modules patch
            raise ImportError(
                "anthropic SDK not installed (pip install seerflow[llm-cloud])"
            ) from exc
        if anthropic is None:  # ``sys.modules[...] = None`` poisons the lookup
            raise ImportError("anthropic SDK not installed (pip install seerflow[llm-cloud])")
        self.model = model
        self.timeout_s = float(timeout_s)
        self.base_url = base_url
        # Snapshot the SDK module so error-handler can reach exception types
        # and ``NOT_GIVEN`` without a second import.
        self._sdk = anthropic
        self._not_given = anthropic.NOT_GIVEN
        self._client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
        stop: tuple[str, ...] = (),
    ) -> str:
        """Single-shot completion. One API call, no retries beyond the SDK's own."""
        capped = min(int(max_tokens), CLOUD_MAX_TOKENS_HARD_CAP)
        stop_sequences: Any = list(stop) if stop else self._not_given
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": capped,
            "temperature": float(temperature),
            "timeout": self.timeout_s,
            "stop_sequences": stop_sequences,
        }
        t0 = time.monotonic()
        try:
            response = await self._client.messages.create(**kwargs)
        except self._sdk.APIStatusError as exc:
            url = _provider_endpoint_url("anthropic", self.base_url)
            snippet = _stringify_body(getattr(exc, "body", None))
            status = getattr(exc, "status_code", 0)
            raise CloudBackendError(
                f"anthropic: HTTP {status} from {_scrub(url)}: {_scrub(snippet)}"
            ) from exc
        except (self._sdk.APIConnectionError, TimeoutError, OSError) as exc:
            # ``TimeoutError`` covers both ``asyncio.TimeoutError`` (PEP 678
            # alias in 3.11+) and the SDK's own ``APITimeoutError`` (which
            # subclasses ``APIConnectionError``). One arm, every case.
            url = _provider_endpoint_url("anthropic", self.base_url)
            raise CloudBackendError(
                f"anthropic: request to {_scrub(url)} failed: {_scrub(repr(exc))}"
            ) from exc
        latency_ms = (time.monotonic() - t0) * 1000.0
        text = self._extract_text(response)
        _log.debug(
            "anthropic: complete model=%s tokens=%d latency_ms=%.1f",
            self.model,
            capped,
            latency_ms,
        )
        return text

    def _extract_text(self, response: Any) -> str:
        """Pull the first text block out of an Anthropic Messages response."""
        url = _provider_endpoint_url("anthropic", self.base_url)
        content = getattr(response, "content", None)
        if not isinstance(content, list) or not content:
            raise CloudBackendError(
                f"anthropic: malformed response from {_scrub(url)}: empty or missing 'content'"
            )
        block = content[0]
        block_type = getattr(block, "type", None)
        if block_type != "text":
            raise CloudBackendError(
                f"anthropic: malformed response from {_scrub(url)}: "
                f"first block type {block_type!r}, expected 'text'"
            )
        text = getattr(block, "text", None)
        if not isinstance(text, str):
            raise CloudBackendError(
                f"anthropic: malformed response from {_scrub(url)}: "
                f"'text' is {type(text).__name__}, expected str"
            )
        return text


class OpenAIBackend:
    """``LLMBackend`` talking to OpenAI (or OpenAI-compatible) chat completions.

    Concurrent calls are safe — the SDK client is documented as
    concurrent-safe. The ``base_url`` knob lets operators point at Azure
    OpenAI, Groq, Together, vLLM, etc.
    """

    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_s: float = 30.0,
        base_url: str | None = None,
    ) -> None:
        try:
            import openai  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised via sys.modules patch
            raise ImportError(
                "openai SDK not installed (pip install seerflow[llm-cloud])"
            ) from exc
        if openai is None:
            raise ImportError("openai SDK not installed (pip install seerflow[llm-cloud])")
        self.model = model
        self.timeout_s = float(timeout_s)
        self.base_url = base_url
        self._sdk = openai
        self._not_given = openai.NOT_GIVEN
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
        stop: tuple[str, ...] = (),
    ) -> str:
        capped = min(int(max_tokens), CLOUD_MAX_TOKENS_HARD_CAP)
        stop_kwarg: Any = list(stop) if stop else self._not_given
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": capped,
            "temperature": float(temperature),
            "timeout": self.timeout_s,
            "stop": stop_kwarg,
        }
        t0 = time.monotonic()
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except self._sdk.APIStatusError as exc:
            url = _provider_endpoint_url("openai", self.base_url)
            snippet = _stringify_body(getattr(exc, "body", None))
            status = getattr(exc, "status_code", 0)
            raise CloudBackendError(
                f"openai: HTTP {status} from {_scrub(url)}: {_scrub(snippet)}"
            ) from exc
        except (self._sdk.APIConnectionError, TimeoutError, OSError) as exc:
            # ``TimeoutError`` covers ``asyncio.TimeoutError`` (PEP 678 alias
            # in 3.11+) and the SDK's ``APITimeoutError`` (subclass of
            # ``APIConnectionError``). One arm, every case.
            url = _provider_endpoint_url("openai", self.base_url)
            raise CloudBackendError(
                f"openai: request to {_scrub(url)} failed: {_scrub(repr(exc))}"
            ) from exc
        latency_ms = (time.monotonic() - t0) * 1000.0
        text = self._extract_text(response)
        _log.debug(
            "openai: complete model=%s tokens=%d latency_ms=%.1f",
            self.model,
            capped,
            latency_ms,
        )
        return text

    def _extract_text(self, response: Any) -> str:
        url = _provider_endpoint_url("openai", self.base_url)
        choices = getattr(response, "choices", None)
        if not isinstance(choices, list) or not choices:
            raise CloudBackendError(
                f"openai: malformed response from {_scrub(url)}: empty or missing 'choices'"
            )
        message = getattr(choices[0], "message", None)
        if message is None:
            raise CloudBackendError(
                f"openai: malformed response from {_scrub(url)}: missing 'message'"
            )
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            raise CloudBackendError(
                f"openai: malformed response from {_scrub(url)}: "
                f"'content' is {type(content).__name__}, expected str"
            )
        return content


__all__ = [
    "CLOUD_MAX_TOKENS_HARD_CAP",
    "AnthropicBackend",
    "CloudBackendError",
    "OpenAIBackend",
]
