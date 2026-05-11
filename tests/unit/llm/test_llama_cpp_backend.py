"""Unit tests for ``LlamaCppBackend`` (S-070 Task 3).

The real ``llama-cpp-python`` wheel is an optional dependency and is never
installed in CI. Every test here monkeypatches ``llama_cpp`` into
``sys.modules`` with a tiny fake whose ``Llama.create_completion`` we drive
from the test.
"""

from __future__ import annotations

import asyncio
import sys
import time
import types
from typing import TYPE_CHECKING, Any

import pytest

from seerflow.llm.backends.llama_cpp import (
    LLAMA_CPP_MAX_TOKENS_HARD_CAP,
    LlamaCppBackend,
    _resolve_n_threads,
)

if TYPE_CHECKING:
    from pathlib import Path


class _FakeLlama:
    """Records constructor + completion kwargs for assertions."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.completion_calls: list[dict[str, Any]] = []
        self.completion_return: dict[str, Any] = {"choices": [{"text": "  hello world"}]}
        self.block_seconds: float = 0.0
        self._active = 0
        self.max_concurrent_observed = 0

    def create_completion(self, prompt: str, **kwargs: Any) -> Any:
        self._active += 1
        if self._active > self.max_concurrent_observed:
            self.max_concurrent_observed = self._active
        try:
            self.completion_calls.append({"prompt": prompt, **kwargs})
            if self.block_seconds:
                time.sleep(self.block_seconds)
            return self.completion_return
        finally:
            self._active -= 1


@pytest.fixture
def fake_llama(monkeypatch: pytest.MonkeyPatch) -> _FakeLlama:
    """Install a fake ``llama_cpp`` module with a single recordable Llama."""
    instances: list[_FakeLlama] = []

    def _factory(**kwargs: Any) -> _FakeLlama:
        inst = _FakeLlama(**kwargs)
        instances.append(inst)
        return inst

    fake_module = types.ModuleType("llama_cpp")
    fake_module.Llama = _factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)

    # Tests need to read back the *constructed* instance after
    # ``complete(...)``. Return a closure that resolves on demand.
    class _Latest:
        def __getattr__(self, name: str) -> Any:
            return getattr(instances[-1], name)

    return _Latest()  # type: ignore[return-value]


@pytest.mark.unit
def test_resolve_n_threads_passthrough() -> None:
    assert _resolve_n_threads(7) == 7


@pytest.mark.unit
def test_resolve_n_threads_none_leaves_one_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("os.cpu_count", lambda: 4)
    assert _resolve_n_threads(None) == 3


@pytest.mark.unit
def test_resolve_n_threads_cpu_count_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.cpu_count", lambda: None)
    # ``or 1`` floor, then ``-1``, clamped to ``max(1, ...)`` → 1.
    assert _resolve_n_threads(None) == 1


@pytest.mark.unit
def test_constructor_does_not_load_model(tmp_path: Path) -> None:
    """Lazy load — the ``Llama`` factory must not be touched at construct time."""
    backend = LlamaCppBackend(tmp_path / "fake.gguf", n_threads=2)
    assert backend.model_path == tmp_path / "fake.gguf"
    assert backend.n_threads == 2
    assert backend._llm is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_invokes_create_completion_once(tmp_path: Path, fake_llama: Any) -> None:
    backend = LlamaCppBackend(tmp_path / "m.gguf", n_threads=2)
    out = await backend.complete("hi", max_tokens=10, temperature=0.5, stop=("\n",))
    # default fake returns "  hello world" (no prompt prefix) → returned verbatim.
    assert out == "  hello world"
    assert len(fake_llama.completion_calls) == 1
    call = fake_llama.completion_calls[0]
    assert call["prompt"] == "hi"
    assert call["max_tokens"] == 10
    assert call["temperature"] == 0.5
    assert call["stop"] == ["\n"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_hard_caps_max_tokens(tmp_path: Path, fake_llama: Any) -> None:
    backend = LlamaCppBackend(tmp_path / "m.gguf", n_threads=2)
    await backend.complete("hi", max_tokens=99999)
    assert fake_llama.completion_calls[0]["max_tokens"] == LLAMA_CPP_MAX_TOKENS_HARD_CAP


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_strips_prompt_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Some quant builds return ``prompt + completion``; the backend strips."""

    class _PrefixingFake:
        def __init__(self, **_: Any) -> None:
            pass

        def create_completion(self, prompt: str, **_: Any) -> Any:
            return {"choices": [{"text": prompt + "  hello world"}]}

    fake_module = types.ModuleType("llama_cpp")
    fake_module.Llama = _PrefixingFake  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)

    backend = LlamaCppBackend(tmp_path / "m.gguf", n_threads=2)
    out = await backend.complete("hi")
    assert out == "  hello world"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_handles_missing_choices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defensive — malformed payloads return empty string, no exception."""

    class _BadFake:
        def __init__(self, **_: Any) -> None:
            pass

        def create_completion(self, prompt: str, **_: Any) -> Any:
            return {"choices": []}

    fake_module = types.ModuleType("llama_cpp")
    fake_module.Llama = _BadFake  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)

    backend = LlamaCppBackend(tmp_path / "m.gguf", n_threads=2)
    out = await backend.complete("hi")
    assert out == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_handles_non_dict_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _StrFake:
        def __init__(self, **_: Any) -> None:
            pass

        def create_completion(self, prompt: str, **_: Any) -> Any:
            return "raw string payload"

    fake_module = types.ModuleType("llama_cpp")
    fake_module.Llama = _StrFake  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)

    backend = LlamaCppBackend(tmp_path / "m.gguf", n_threads=2)
    out = await backend.complete("hi")
    assert out == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_runs_in_thread(tmp_path: Path, fake_llama: Any) -> None:
    """A blocking sync call must not stall the event loop."""
    backend = LlamaCppBackend(tmp_path / "m.gguf", n_threads=2)

    # Prime the lazy load + capture the constructed fake instance.
    await backend.complete("warm-up")
    fake_llama.block_seconds = 0.05  # type: ignore[attr-defined]

    ticks = {"count": 0}

    async def _ticker() -> None:
        for _ in range(20):
            await asyncio.sleep(0.005)
            ticks["count"] += 1

    ticker = asyncio.create_task(_ticker())
    await backend.complete("blocking")
    await ticker
    assert ticks["count"] >= 1, "Event loop stalled — to_thread offload broken"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_serialises_concurrent_calls(tmp_path: Path, fake_llama: Any) -> None:
    """Concurrent ``complete(...)`` calls share one instance; never overlap."""
    backend = LlamaCppBackend(tmp_path / "m.gguf", n_threads=2)

    # Prime so both concurrent calls see the same instance.
    await backend.complete("warm-up")
    fake_llama.block_seconds = 0.02  # type: ignore[attr-defined]

    await asyncio.gather(backend.complete("a"), backend.complete("b"), backend.complete("c"))
    assert fake_llama.max_concurrent_observed == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_constructor_passes_kwargs_to_llama(tmp_path: Path, fake_llama: Any) -> None:
    backend = LlamaCppBackend(
        tmp_path / "m.gguf",
        n_ctx=2048,
        n_threads=1,
        n_gpu_layers=4,
        seed=7,
        logits_all=True,
        verbose=True,
    )
    await backend.complete("hi")
    kwargs = fake_llama.kwargs  # type: ignore[attr-defined]
    assert kwargs["model_path"] == str(tmp_path / "m.gguf")
    assert kwargs["n_ctx"] == 2048
    assert kwargs["n_threads"] == 1
    assert kwargs["n_gpu_layers"] == 4
    assert kwargs["seed"] == 7
    assert kwargs["logits_all"] is True
    assert kwargs["verbose"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lazy_load_logs_once(
    tmp_path: Path,
    fake_llama: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = LlamaCppBackend(tmp_path / "m.gguf", n_threads=2)
    caplog.set_level("INFO", logger="seerflow.llm.backends.llama_cpp")
    await backend.complete("a")
    await backend.complete("b")
    load_logs = [r for r in caplog.records if "model_loaded" in r.getMessage()]
    assert len(load_logs) == 1, "model_loaded should log exactly once"
