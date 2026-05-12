"""Unit tests for the Ollama LLM backend (S-098).

Every test is offline: ``aioresponses`` mocks at the ``aiohttp`` request
layer, and the transport-error paths monkeypatch ``aiohttp.ClientSession.post``
directly. No real network I/O is performed.
"""

from __future__ import annotations

import json
import re
from typing import Any

import aiohttp
import pytest
from aioresponses import aioresponses

from seerflow.llm.backends.ollama import (
    OLLAMA_MAX_TOKENS_HARD_CAP,
    OllamaBackend,
    OllamaBackendError,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


async def test_happy_path_returns_response_field() -> None:
    """``complete`` returns the ``response`` field from ``/api/generate``."""
    backend = OllamaBackend("http://test", "phi4-mini")
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            payload={"response": "  Yes."},
            content_type="application/json",
        )
        result = await backend.complete("Is it raining?")
    assert result == "  Yes."


async def test_request_body_default_shape() -> None:
    """Default request body has expected ``options`` and no ``stop`` key."""
    captured: dict[str, Any] = {}

    def _capture(url: str, **kwargs: Any) -> None:
        captured["url"] = str(url)
        body = kwargs.get("json")
        if body is None and kwargs.get("data") is not None:
            body = json.loads(kwargs["data"])
        captured["body"] = body

    backend = OllamaBackend("http://test", "phi4-mini")
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            payload={"response": "ok"},
            content_type="application/json",
            callback=_capture,
        )
        await backend.complete("hello")
    body = captured["body"]
    assert body["model"] == "phi4-mini"
    assert body["prompt"] == "hello"
    assert body["stream"] is False
    assert body["options"]["num_predict"] == 256
    assert body["options"]["temperature"] == pytest.approx(0.2)
    assert "stop" not in body["options"]


# --------------------------------------------------------------------------- #
# Arg edge cases                                                              #
# --------------------------------------------------------------------------- #


async def test_max_tokens_clamped_to_hard_cap() -> None:
    captured: dict[str, Any] = {}

    def _capture(url: str, **kwargs: Any) -> None:
        body = kwargs.get("json")
        if body is None and kwargs.get("data") is not None:
            body = json.loads(kwargs["data"])
        captured["body"] = body

    backend = OllamaBackend("http://test", "m")
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            payload={"response": "ok"},
            callback=_capture,
        )
        await backend.complete("p", max_tokens=99999)
    assert captured["body"]["options"]["num_predict"] == OLLAMA_MAX_TOKENS_HARD_CAP
    assert OLLAMA_MAX_TOKENS_HARD_CAP == 1024


async def test_stop_tokens_passed_when_non_empty() -> None:
    captured: dict[str, Any] = {}

    def _capture(url: str, **kwargs: Any) -> None:
        body = kwargs.get("json")
        if body is None and kwargs.get("data") is not None:
            body = json.loads(kwargs["data"])
        captured["body"] = body

    backend = OllamaBackend("http://test", "m")
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            payload={"response": "ok"},
            callback=_capture,
        )
        await backend.complete("p", stop=("\n", "###"))
    assert captured["body"]["options"]["stop"] == ["\n", "###"]


async def test_empty_stop_tuple_omits_key() -> None:
    captured: dict[str, Any] = {}

    def _capture(url: str, **kwargs: Any) -> None:
        body = kwargs.get("json")
        if body is None and kwargs.get("data") is not None:
            body = json.loads(kwargs["data"])
        captured["body"] = body

    backend = OllamaBackend("http://test", "m")
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            payload={"response": "ok"},
            callback=_capture,
        )
        await backend.complete("p", stop=())
    assert "stop" not in captured["body"]["options"]


async def test_temperature_passed_through() -> None:
    captured: dict[str, Any] = {}

    def _capture(url: str, **kwargs: Any) -> None:
        body = kwargs.get("json")
        if body is None and kwargs.get("data") is not None:
            body = json.loads(kwargs["data"])
        captured["body"] = body

    backend = OllamaBackend("http://test", "m")
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            payload={"response": "ok"},
            callback=_capture,
        )
        await backend.complete("p", temperature=0.5)
    assert captured["body"]["options"]["temperature"] == pytest.approx(0.5)


async def test_prompt_prefix_stripped_when_present() -> None:
    backend = OllamaBackend("http://test", "m")
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            payload={"response": "Q?\n  Yes."},
        )
        result = await backend.complete("Q?\n")
    assert result == "  Yes."


async def test_trailing_slash_base_url_no_double_slash() -> None:
    captured: dict[str, Any] = {}

    def _capture(url: str, **kwargs: Any) -> None:
        captured["url"] = str(url)

    backend = OllamaBackend("http://test/", "m")
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            payload={"response": "ok"},
            callback=_capture,
        )
        await backend.complete("p")
    assert captured["url"] == "http://test/api/generate"


async def test_name_attribute_is_ollama() -> None:
    backend = OllamaBackend("http://test", "m")
    assert backend.name == "ollama"


async def test_satisfies_llm_backend_protocol() -> None:
    """AC1: ``OllamaBackend`` is a valid ``LLMBackend`` at runtime."""
    from seerflow.llm.protocol import LLMBackend

    backend = OllamaBackend("http://test", "m")
    assert isinstance(backend, LLMBackend)


# --------------------------------------------------------------------------- #
# Error paths                                                                 #
# --------------------------------------------------------------------------- #


async def test_http_404_raises_backend_error_with_body_snippet() -> None:
    backend = OllamaBackend("http://test", "m")
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            status=404,
            body='{"error":"model not found"}',
            content_type="application/json",
        )
        with pytest.raises(OllamaBackendError) as exc:
            await backend.complete("p")
    msg = str(exc.value)
    assert "HTTP 404" in msg
    assert "model not found" in msg


async def test_timeout_raises_backend_error() -> None:
    backend = OllamaBackend("http://test", "m", timeout_s=1.0)
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            exception=TimeoutError("slow"),
        )
        with pytest.raises(OllamaBackendError) as exc:
            await backend.complete("p")
    assert str(exc.value).startswith("ollama:")


async def test_connector_error_raises_backend_error() -> None:
    backend = OllamaBackend("http://test", "m")
    with aioresponses() as mock:
        # ``aioresponses`` raises any exception we give it from the matched POST.
        mock.post(
            "http://test/api/generate",
            exception=aiohttp.ClientError("connection refused"),
        )
        with pytest.raises(OllamaBackendError) as exc:
            await backend.complete("p")
    assert "ollama:" in str(exc.value)


async def test_malformed_non_json_body_raises() -> None:
    backend = OllamaBackend("http://test", "m")
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            body="not-json",
            content_type="text/plain",
        )
        with pytest.raises(OllamaBackendError, match=r"malformed response"):
            await backend.complete("p")


async def test_missing_response_key_raises() -> None:
    backend = OllamaBackend("http://test", "m")
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            payload={"foo": "bar"},
            content_type="application/json",
        )
        with pytest.raises(OllamaBackendError, match=r"malformed response"):
            await backend.complete("p")


async def test_non_string_response_raises() -> None:
    backend = OllamaBackend("http://test", "m")
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            payload={"response": 42},
            content_type="application/json",
        )
        with pytest.raises(OllamaBackendError, match=r"malformed response"):
            await backend.complete("p")


async def test_error_message_scrubs_bearer_token() -> None:
    """``OllamaBackendError`` never leaks a ``Bearer`` substring.

    Regression guard: if a future caller passes a URL containing an
    ``Authorization`` query parameter (or the underlying ``aiohttp`` repr
    leaks one), the wrapped error must redact it via ``_scrub``.
    """
    backend = OllamaBackend("http://test", "m")

    # Make the transport raise a ClientError whose ``repr`` contains a Bearer
    # blob. The backend wraps it via ``_scrub(repr(exc))`` which must redact.
    class _LeakyError(aiohttp.ClientError):
        def __repr__(self) -> str:
            return "_LeakyError('boom Authorization: Bearer leaky-token-1234 trailing')"

    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            exception=_LeakyError(),
        )
        with pytest.raises(OllamaBackendError) as exc:
            await backend.complete("p")
    msg = str(exc.value)
    assert "leaky-token-1234" not in msg
    assert not re.search(r"Bearer\s+\S+(?!<redacted>)", msg) or "<redacted>" in msg


async def test_error_message_scrubs_url_embedded_userinfo() -> None:
    """Defence-in-depth: ``user:pass@host`` in the URL is redacted in errors.

    Ollama itself doesn't ship auth, but an operator placing it behind a
    reverse proxy might embed credentials. We must not leak them in the
    error message.
    """
    backend = OllamaBackend("http://admin:hunter2@gpu-host:11434", "m")
    with aioresponses() as mock:
        mock.post(
            "http://admin:hunter2@gpu-host:11434/api/generate",
            exception=aiohttp.ClientError("boom"),
        )
        with pytest.raises(OllamaBackendError) as exc:
            await backend.complete("p")
    msg = str(exc.value)
    assert "hunter2" not in msg
    assert "admin:hunter2" not in msg
    assert "<redacted>" in msg


async def test_http_error_body_snippet_truncated_to_200_chars() -> None:
    backend = OllamaBackend("http://test", "m")
    long_body = "x" * 1000
    with aioresponses() as mock:
        mock.post(
            "http://test/api/generate",
            status=500,
            body=long_body,
            content_type="text/plain",
        )
        with pytest.raises(OllamaBackendError) as exc:
            await backend.complete("p")
    msg = str(exc.value)
    # Snippet should be capped — full 1000 chars must not appear.
    assert "x" * 1000 not in msg
    assert "HTTP 500" in msg
