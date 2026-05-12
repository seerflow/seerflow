"""Unit tests for the cloud LLM backends (S-099).

Covers ``AnthropicBackend`` and ``OpenAIBackend``: happy paths, parameter
pass-through, error handling, secret scrubbing, lazy-import safety.

The official Anthropic / OpenAI SDKs are *optional* dependencies. Every test
in this module either monkeypatches the SDK or skips when the real SDK is
absent — the test suite must run cleanly without the cloud extra installed.
"""

from __future__ import annotations

import logging
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

from seerflow.llm.backends.cloud import (
    CLOUD_MAX_TOKENS_HARD_CAP,
    AnthropicBackend,
    CloudBackendError,
    OpenAIBackend,
)
from seerflow.llm.protocol import LLMBackend

# ---------------------------------------------------------------------------
# Fakes that emulate the SDK surface used by the backends.
# ---------------------------------------------------------------------------


class _FakeAnthropicMessages:
    """Captures ``messages.create`` kwargs + returns a configured response."""

    def __init__(self, *, response: Any = None, raises: BaseException | None = None) -> None:
        self.response = response
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return self.response


class _FakeAsyncAnthropic:
    """Stand-in for ``anthropic.AsyncAnthropic``."""

    last_init_kwargs: dict[str, Any] | None = None

    def __init__(self, **kwargs: Any) -> None:
        type(self).last_init_kwargs = dict(kwargs)
        self.messages = _FakeAnthropicMessages(
            response=type(self)._next_response,
            raises=type(self)._next_raises,
        )

    # The class-level slots let tests configure the next constructed instance.
    _next_response: Any = None
    _next_raises: BaseException | None = None


class _FakeOpenAICompletions:
    def __init__(self, *, response: Any = None, raises: BaseException | None = None) -> None:
        self.response = response
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return self.response


class _FakeOpenAIChat:
    def __init__(self, completions: _FakeOpenAICompletions) -> None:
        self.completions = completions


class _FakeAsyncOpenAI:
    """Stand-in for ``openai.AsyncOpenAI``."""

    last_init_kwargs: dict[str, Any] | None = None

    def __init__(self, **kwargs: Any) -> None:
        type(self).last_init_kwargs = dict(kwargs)
        self.chat = _FakeOpenAIChat(
            _FakeOpenAICompletions(
                response=type(self)._next_response,
                raises=type(self)._next_raises,
            )
        )

    _next_response: Any = None
    _next_raises: BaseException | None = None


def _set_fake_anthropic(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: Any = None,
    raises: BaseException | None = None,
    not_given: Any = "<NOT_GIVEN>",
) -> type[_FakeAsyncAnthropic]:
    """Install the fake on a synthetic ``anthropic`` module."""
    _FakeAsyncAnthropic._next_response = response
    _FakeAsyncAnthropic._next_raises = raises
    _FakeAsyncAnthropic.last_init_kwargs = None

    fake_mod = types.ModuleType("anthropic")
    fake_mod.AsyncAnthropic = _FakeAsyncAnthropic  # type: ignore[attr-defined]
    fake_mod.NOT_GIVEN = not_given  # type: ignore[attr-defined]

    # Minimal exception hierarchy that the backend imports.
    class APIStatusError(Exception):
        def __init__(
            self,
            message: str = "",
            *,
            status_code: int = 0,
            response: Any = None,
            body: Any = None,
        ) -> None:
            super().__init__(message)
            self.status_code = status_code
            self.response = response
            self.body = body

    class APIConnectionError(Exception):
        def __init__(self, message: str = "", *, request: Any = None) -> None:
            super().__init__(message)
            self.request = request

    fake_mod.APIStatusError = APIStatusError  # type: ignore[attr-defined]
    fake_mod.APIConnectionError = APIConnectionError  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "anthropic", fake_mod)
    return _FakeAsyncAnthropic


def _set_fake_openai(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: Any = None,
    raises: BaseException | None = None,
    not_given: Any = "<NOT_GIVEN>",
) -> type[_FakeAsyncOpenAI]:
    """Install the fake on a synthetic ``openai`` module."""
    _FakeAsyncOpenAI._next_response = response
    _FakeAsyncOpenAI._next_raises = raises
    _FakeAsyncOpenAI.last_init_kwargs = None

    fake_mod = types.ModuleType("openai")
    fake_mod.AsyncOpenAI = _FakeAsyncOpenAI  # type: ignore[attr-defined]
    fake_mod.NOT_GIVEN = not_given  # type: ignore[attr-defined]

    class APIStatusError(Exception):
        def __init__(
            self,
            message: str = "",
            *,
            status_code: int = 0,
            response: Any = None,
            body: Any = None,
        ) -> None:
            super().__init__(message)
            self.status_code = status_code
            self.response = response
            self.body = body

    class APIConnectionError(Exception):
        def __init__(self, message: str = "", *, request: Any = None) -> None:
            super().__init__(message)
            self.request = request

    fake_mod.APIStatusError = APIStatusError  # type: ignore[attr-defined]
    fake_mod.APIConnectionError = APIConnectionError  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "openai", fake_mod)
    return _FakeAsyncOpenAI


def _anthropic_response(text: str, *, block_type: str = "text") -> Any:
    return SimpleNamespace(content=[SimpleNamespace(type=block_type, text=text)])


def _openai_response(text: str | None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


# ---------------------------------------------------------------------------
# AnthropicBackend tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cls = _set_fake_anthropic(monkeypatch, response=_anthropic_response("  Yes."))

    backend = AnthropicBackend(api_key="sk-test", model="claude-haiku-4-5")
    out = await backend.complete("Is it raining?")

    assert out == "  Yes."
    assert backend.name == "anthropic"
    assert fake_cls.last_init_kwargs == {"api_key": "sk-test", "base_url": None}
    assert isinstance(backend, LLMBackend)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_default_kwargs_match_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fake_anthropic(monkeypatch, response=_anthropic_response("ok"))
    backend = AnthropicBackend(api_key="k", model="claude-haiku-4-5")
    await backend.complete("hi")

    client = backend._client  # type: ignore[attr-defined]
    call = client.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert call["messages"] == [{"role": "user", "content": "hi"}]
    assert call["max_tokens"] == 256
    assert call["temperature"] == pytest.approx(0.2)
    assert call["timeout"] == pytest.approx(30.0)
    # ``stop`` empty → kwarg passed as the SDK sentinel (``NOT_GIVEN``).
    assert call["stop_sequences"] == "<NOT_GIVEN>"


# ---------------------------------------------------------------------------
# OpenAIBackend tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cls = _set_fake_openai(monkeypatch, response=_openai_response("  Yes."))

    backend = OpenAIBackend(api_key="sk-test", model="gpt-4o-mini")
    out = await backend.complete("Is it raining?")

    assert out == "  Yes."
    assert backend.name == "openai"
    assert fake_cls.last_init_kwargs == {"api_key": "sk-test", "base_url": None}
    assert isinstance(backend, LLMBackend)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_default_kwargs_match_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fake_openai(monkeypatch, response=_openai_response("ok"))
    backend = OpenAIBackend(api_key="k", model="gpt-4o-mini")
    await backend.complete("hi")

    client = backend._client  # type: ignore[attr-defined]
    call = client.chat.completions.calls[0]
    assert call["model"] == "gpt-4o-mini"
    assert call["messages"] == [{"role": "user", "content": "hi"}]
    assert call["max_tokens"] == 256
    assert call["temperature"] == pytest.approx(0.2)
    assert call["timeout"] == pytest.approx(30.0)
    assert call["stop"] == "<NOT_GIVEN>"


# ---------------------------------------------------------------------------
# Parameter pass-through (both backends)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_hard_cap_clamps_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fake_anthropic(monkeypatch, response=_anthropic_response("x"))
    backend = AnthropicBackend(api_key="k", model="m")
    await backend.complete("p", max_tokens=99999)
    call = backend._client.messages.calls[0]  # type: ignore[attr-defined]
    assert call["max_tokens"] == CLOUD_MAX_TOKENS_HARD_CAP == 1024


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_hard_cap_clamps_max_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_openai(monkeypatch, response=_openai_response("x"))
    backend = OpenAIBackend(api_key="k", model="m")
    await backend.complete("p", max_tokens=99999)
    call = backend._client.chat.completions.calls[0]  # type: ignore[attr-defined]
    assert call["max_tokens"] == 1024


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_stop_tokens_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fake_anthropic(monkeypatch, response=_anthropic_response("x"))
    backend = AnthropicBackend(api_key="k", model="m")
    await backend.complete("p", stop=("\n", "###"))
    call = backend._client.messages.calls[0]  # type: ignore[attr-defined]
    assert call["stop_sequences"] == ["\n", "###"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_stop_tokens_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_openai(monkeypatch, response=_openai_response("x"))
    backend = OpenAIBackend(api_key="k", model="m")
    await backend.complete("p", stop=("\n", "###"))
    call = backend._client.chat.completions.calls[0]  # type: ignore[attr-defined]
    assert call["stop"] == ["\n", "###"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_temperature_pass_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fake_anthropic(monkeypatch, response=_anthropic_response("x"))
    backend = AnthropicBackend(api_key="k", model="m")
    await backend.complete("p", temperature=0.5)
    call = backend._client.messages.calls[0]  # type: ignore[attr-defined]
    assert call["temperature"] == pytest.approx(0.5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_temperature_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_openai(monkeypatch, response=_openai_response("x"))
    backend = OpenAIBackend(api_key="k", model="m")
    await backend.complete("p", temperature=0.5)
    call = backend._client.chat.completions.calls[0]  # type: ignore[attr-defined]
    assert call["temperature"] == pytest.approx(0.5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_timeout_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_anthropic(monkeypatch, response=_anthropic_response("x"))
    backend = AnthropicBackend(api_key="k", model="m", timeout_s=2.0)
    await backend.complete("p")
    call = backend._client.messages.calls[0]  # type: ignore[attr-defined]
    assert call["timeout"] == pytest.approx(2.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_timeout_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_openai(monkeypatch, response=_openai_response("x"))
    backend = OpenAIBackend(api_key="k", model="m", timeout_s=2.0)
    await backend.complete("p")
    call = backend._client.chat.completions.calls[0]  # type: ignore[attr-defined]
    assert call["timeout"] == pytest.approx(2.0)


@pytest.mark.unit
def test_anthropic_base_url_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cls = _set_fake_anthropic(monkeypatch)
    AnthropicBackend(api_key="k", model="m", base_url="https://proxy.example/")
    assert fake_cls.last_init_kwargs == {
        "api_key": "k",
        "base_url": "https://proxy.example/",
    }


@pytest.mark.unit
def test_openai_base_url_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cls = _set_fake_openai(monkeypatch)
    OpenAIBackend(api_key="k", model="m", base_url="https://proxy.example/")
    assert fake_cls.last_init_kwargs == {
        "api_key": "k",
        "base_url": "https://proxy.example/",
    }


# ---------------------------------------------------------------------------
# Error-path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_api_status_error_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cls = _set_fake_anthropic(monkeypatch, response=_anthropic_response("ok"))
    import anthropic  # type: ignore[import-not-found]

    api_err = anthropic.APIStatusError(  # type: ignore[attr-defined]
        "rate limit",
        status_code=429,
        response=None,
        body={"error": {"message": "Too many requests"}},
    )
    _FakeAsyncAnthropic._next_raises = api_err  # next instance will raise
    # Force a fresh client by constructing the backend after configuring raises:
    backend = AnthropicBackend(api_key="k", model="m")

    with pytest.raises(CloudBackendError) as excinfo:
        await backend.complete("p")
    msg = str(excinfo.value)
    assert "anthropic" in msg
    assert "HTTP 429" in msg
    assert "Too many requests" in msg
    assert fake_cls is _FakeAsyncAnthropic  # silence unused


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_api_status_error_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_openai(monkeypatch, response=_openai_response("ok"))
    import openai  # type: ignore[import-not-found]

    api_err = openai.APIStatusError(  # type: ignore[attr-defined]
        "bad request",
        status_code=400,
        response=None,
        body={"error": {"message": "Invalid model"}},
    )
    _FakeAsyncOpenAI._next_raises = api_err
    backend = OpenAIBackend(api_key="k", model="m")

    with pytest.raises(CloudBackendError) as excinfo:
        await backend.complete("p")
    msg = str(excinfo.value)
    assert "openai" in msg
    assert "HTTP 400" in msg
    assert "Invalid model" in msg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_connection_error_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fake_anthropic(monkeypatch)
    import anthropic  # type: ignore[import-not-found]

    _FakeAsyncAnthropic._next_raises = anthropic.APIConnectionError(  # type: ignore[attr-defined]
        "Connection refused"
    )
    backend = AnthropicBackend(api_key="k", model="m")

    with pytest.raises(CloudBackendError) as excinfo:
        await backend.complete("p")
    msg = str(excinfo.value)
    assert msg.startswith("anthropic: request to")
    assert "failed" in msg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_connection_error_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_openai(monkeypatch)
    import openai  # type: ignore[import-not-found]

    _FakeAsyncOpenAI._next_raises = openai.APIConnectionError("Connection refused")  # type: ignore[attr-defined]
    backend = OpenAIBackend(api_key="k", model="m")

    with pytest.raises(CloudBackendError) as excinfo:
        await backend.complete("p")
    assert str(excinfo.value).startswith("openai: request to")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_timeout_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_anthropic(monkeypatch)
    _FakeAsyncAnthropic._next_raises = TimeoutError("deadline exceeded")
    backend = AnthropicBackend(api_key="k", model="m")
    with pytest.raises(CloudBackendError) as excinfo:
        await backend.complete("p")
    assert str(excinfo.value).startswith("anthropic:")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_timeout_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_openai(monkeypatch)
    _FakeAsyncOpenAI._next_raises = TimeoutError("deadline exceeded")
    backend = OpenAIBackend(api_key="k", model="m")
    with pytest.raises(CloudBackendError) as excinfo:
        await backend.complete("p")
    assert str(excinfo.value).startswith("openai:")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_malformed_empty_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fake_anthropic(monkeypatch, response=SimpleNamespace(content=[]))
    backend = AnthropicBackend(api_key="k", model="m")
    with pytest.raises(CloudBackendError, match="malformed response"):
        await backend.complete("p")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_malformed_non_text_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fake_anthropic(
        monkeypatch,
        response=SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", text="ignored")]
        ),
    )
    backend = AnthropicBackend(api_key="k", model="m")
    with pytest.raises(CloudBackendError, match="malformed response"):
        await backend.complete("p")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_malformed_text_not_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fake_anthropic(
        monkeypatch,
        response=SimpleNamespace(content=[SimpleNamespace(type="text", text=42)]),
    )
    backend = AnthropicBackend(api_key="k", model="m")
    with pytest.raises(CloudBackendError, match="malformed response"):
        await backend.complete("p")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_malformed_none_content(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_openai(monkeypatch, response=_openai_response(None))
    backend = OpenAIBackend(api_key="k", model="m")
    with pytest.raises(CloudBackendError, match="malformed response"):
        await backend.complete("p")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_malformed_empty_choices(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_openai(monkeypatch, response=SimpleNamespace(choices=[]))
    backend = OpenAIBackend(api_key="k", model="m")
    with pytest.raises(CloudBackendError, match="malformed response"):
        await backend.complete("p")


# ---------------------------------------------------------------------------
# Secret-scrubbing
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_error_message_scrubs_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fake_anthropic(monkeypatch)
    import anthropic  # type: ignore[import-not-found]

    _FakeAsyncAnthropic._next_raises = anthropic.APIConnectionError(  # type: ignore[attr-defined]
        "auth header was Bearer sk-test-secret-token-xyz"
    )
    backend = AnthropicBackend(api_key="k", model="m")

    with pytest.raises(CloudBackendError) as excinfo:
        await backend.complete("p")
    msg = str(excinfo.value)
    assert "Bearer <redacted>" in msg
    assert "sk-test-secret-token-xyz" not in msg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_error_message_scrubs_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_fake_openai(monkeypatch)
    import openai  # type: ignore[import-not-found]

    _FakeAsyncOpenAI._next_raises = openai.APIConnectionError(  # type: ignore[attr-defined]
        "auth header was Bearer sk-openai-test-token-xyz"
    )
    backend = OpenAIBackend(api_key="k", model="m")

    with pytest.raises(CloudBackendError) as excinfo:
        await backend.complete("p")
    msg = str(excinfo.value)
    assert "Bearer <redacted>" in msg
    assert "sk-openai-test-token-xyz" not in msg


# ---------------------------------------------------------------------------
# Lazy-import safety + ImportError surfacing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_module_imports_without_sdks_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """``import seerflow.llm.backends.cloud`` succeeds when SDKs are absent."""
    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.delitem(sys.modules, "seerflow.llm.backends.cloud", raising=False)
    import importlib

    mod = importlib.import_module("seerflow.llm.backends.cloud")
    assert hasattr(mod, "AnthropicBackend")
    assert hasattr(mod, "OpenAIBackend")
    assert hasattr(mod, "CloudBackendError")
    assert mod.CLOUD_MAX_TOKENS_HARD_CAP == 1024


@pytest.mark.unit
def test_anthropic_constructor_raises_importerror_when_sdk_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ImportError):
        AnthropicBackend(api_key="k", model="m")


@pytest.mark.unit
def test_openai_constructor_raises_importerror_when_sdk_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ImportError):
        OpenAIBackend(api_key="k", model="m")


# ---------------------------------------------------------------------------
# DEBUG log + CloudBackendError typing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cloud_backend_error_is_runtime_error() -> None:
    err = CloudBackendError("anthropic: boom")
    assert isinstance(err, RuntimeError)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_debug_log_emitted(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _set_fake_anthropic(monkeypatch, response=_anthropic_response("done"))
    caplog.set_level(logging.DEBUG, logger="seerflow.llm.backends.cloud")
    backend = AnthropicBackend(api_key="k", model="m")
    await backend.complete("p")
    assert any(
        "anthropic" in r.getMessage() and "complete" in r.getMessage()
        for r in caplog.records
        if r.levelno == logging.DEBUG
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_debug_log_emitted(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _set_fake_openai(monkeypatch, response=_openai_response("done"))
    caplog.set_level(logging.DEBUG, logger="seerflow.llm.backends.cloud")
    backend = OpenAIBackend(api_key="k", model="m")
    await backend.complete("p")
    assert any(
        "openai" in r.getMessage() and "complete" in r.getMessage()
        for r in caplog.records
        if r.levelno == logging.DEBUG
    )
