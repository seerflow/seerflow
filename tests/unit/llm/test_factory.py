"""Unit tests for ``build_llm_backend`` (S-070 Task 4, S-098, S-099).

Covers every branch:

- empty backend → ``None`` + INFO ("disabled")
- llama_cpp + missing path → ``None`` + WARNING
- llama_cpp + non-.gguf path → ``None`` + WARNING
- llama_cpp + ImportError → ``None`` + WARNING with install hint
- llama_cpp + non-ImportError → re-raised + ERROR
- llama_cpp + happy path → backend instance
- ollama + valid config → ``OllamaBackend`` instance + INFO log (S-098)
- ollama + empty ollama_url → ``None`` + WARNING (S-098)
- ollama + empty ollama_model → ``None`` + WARNING (S-098)
- cloud + anthropic + valid config → ``AnthropicBackend`` + INFO log (S-099)
- cloud + openai + valid config → ``OpenAIBackend`` + INFO log (S-099)
- cloud + empty cloud_provider → ``None`` + WARNING (S-099)
- cloud + empty cloud_api_key → ``None`` + WARNING (S-099)
- cloud + empty cloud_model → ``None`` + WARNING (S-099)
- cloud + SDK ImportError → ``None`` + WARNING with install hint (S-099)
- unknown backend → ``ConfigError``
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest

from seerflow._config_validation import ConfigError
from seerflow.config import LLMConfig
from seerflow.llm.factory import build_llm_backend

if TYPE_CHECKING:
    from pathlib import Path


def _cfg(**overrides: Any) -> LLMConfig:
    base: dict[str, Any] = {
        "backend": "",
        "model_path": "",
    }
    base.update(overrides)
    return LLMConfig(**base)


@pytest.fixture
def gguf_file(tmp_path: Path) -> Path:
    path = tmp_path / "model.gguf"
    path.write_bytes(b"GGUF")
    return path


@pytest.mark.unit
def test_backend_empty_returns_none_logs_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="seerflow.llm.factory")
    out = build_llm_backend(_cfg())
    assert out is None
    assert any(
        "disabled (no backend configured)" in r.getMessage() and r.levelno == logging.INFO
        for r in caplog.records
    )


@pytest.mark.unit
def test_backend_unknown_raises_config_error() -> None:
    with pytest.raises(ConfigError) as excinfo:
        build_llm_backend(_cfg(backend="garbage"))
    msg = str(excinfo.value)
    assert "'garbage'" in msg
    assert "llama_cpp" in msg
    assert "ollama" in msg
    assert "cloud" in msg


@pytest.mark.unit
def test_backend_ollama_valid_returns_backend_logs_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S-098: ``backend=ollama`` + valid url + model → ``OllamaBackend`` instance."""
    from seerflow.llm.backends.ollama import OllamaBackend

    caplog.set_level(logging.INFO, logger="seerflow.llm.factory")
    out = build_llm_backend(
        _cfg(
            backend="ollama",
            ollama_url="http://localhost:11434",
            ollama_model="phi4-mini",
            ollama_timeout_s=45.0,
        )
    )
    assert isinstance(out, OllamaBackend)
    assert out.name == "ollama"
    assert out.base_url == "http://localhost:11434"
    assert out.model == "phi4-mini"
    assert out.timeout_s == pytest.approx(45.0)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("ollama" in m and "configured backend" in m for m in msgs)
    # The deferred log must not appear once the real branch is wired.
    assert not any("deferred" in m for m in msgs)


@pytest.mark.unit
def test_backend_ollama_empty_url_returns_none_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S-098: empty ``ollama_url`` → graceful absence."""
    caplog.set_level(logging.WARNING, logger="seerflow.llm.factory")
    out = build_llm_backend(_cfg(backend="ollama", ollama_url="", ollama_model="phi4-mini"))
    assert out is None
    assert any("ollama_url" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_backend_ollama_empty_model_returns_none_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S-098: empty ``ollama_model`` → graceful absence."""
    caplog.set_level(logging.WARNING, logger="seerflow.llm.factory")
    out = build_llm_backend(
        _cfg(backend="ollama", ollama_url="http://localhost:11434", ollama_model="")
    )
    assert out is None
    assert any("ollama_model" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_backend_cloud_no_config_returns_none_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S-099: ``backend=cloud`` with no provider configured is graceful absence.

    Rewrites the S-070 ``"deferred"`` placeholder test. The branch is now
    real but degrades cleanly when the operator has not finished wiring
    cloud config.
    """
    caplog.set_level(logging.WARNING, logger="seerflow.llm.factory")
    out = build_llm_backend(_cfg(backend="cloud"))
    assert out is None
    msgs = [r.getMessage() for r in caplog.records]
    assert any("cloud_provider" in m and "missing" in m for m in msgs)
    # The S-070 deferred-INFO log must not appear once the branch is wired.
    assert not any("deferred" in m for m in msgs)


@pytest.mark.unit
def test_backend_cloud_anthropic_valid_returns_backend_logs_info(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S-099: ``cloud`` + ``provider=anthropic`` + key + model → ``AnthropicBackend``."""
    sentinel = object()
    captured: dict[str, Any] = {}

    def _factory(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("seerflow.llm.factory.AnthropicBackend", _factory)
    caplog.set_level(logging.INFO, logger="seerflow.llm.factory")

    out = build_llm_backend(
        _cfg(
            backend="cloud",
            cloud_provider="anthropic",
            cloud_api_key="sk-ant-test",
            cloud_model="claude-haiku-4-5",
            cloud_timeout_s=45.0,
        )
    )
    assert out is sentinel
    assert captured["api_key"] == "sk-ant-test"
    assert captured["model"] == "claude-haiku-4-5"
    assert captured["timeout_s"] == pytest.approx(45.0)
    assert captured["base_url"] is None

    msgs = [r.getMessage() for r in caplog.records]
    info_msgs = [m for m in msgs if "configured backend" in m]
    assert any("provider=anthropic" in m and "model=claude-haiku-4-5" in m for m in info_msgs)
    # The key MUST NOT appear anywhere in the log capture.
    assert not any("sk-ant-test" in m for m in msgs)


@pytest.mark.unit
def test_backend_cloud_openai_valid_returns_backend_logs_info(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S-099: ``cloud`` + ``provider=openai`` + key + model → ``OpenAIBackend``."""
    sentinel = object()
    captured: dict[str, Any] = {}

    def _factory(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("seerflow.llm.factory.OpenAIBackend", _factory)
    caplog.set_level(logging.INFO, logger="seerflow.llm.factory")

    out = build_llm_backend(
        _cfg(
            backend="cloud",
            cloud_provider="openai",
            cloud_api_key="sk-openai-test",
            cloud_model="gpt-4o-mini",
            cloud_base_url="https://proxy.example/",
        )
    )
    assert out is sentinel
    assert captured["api_key"] == "sk-openai-test"
    assert captured["model"] == "gpt-4o-mini"
    assert captured["base_url"] == "https://proxy.example/"

    msgs = [r.getMessage() for r in caplog.records]
    assert any("provider=openai" in m and "model=gpt-4o-mini" in m for m in msgs)
    assert not any("sk-openai-test" in m for m in msgs)


@pytest.mark.unit
def test_backend_cloud_empty_api_key_returns_none_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S-099: empty ``cloud_api_key`` → graceful absence + WARNING."""
    caplog.set_level(logging.WARNING, logger="seerflow.llm.factory")
    out = build_llm_backend(
        _cfg(
            backend="cloud",
            cloud_provider="anthropic",
            cloud_api_key="",
            cloud_model="claude-haiku-4-5",
        )
    )
    assert out is None
    msgs = [r.getMessage() for r in caplog.records]
    assert any("cloud_api_key" in m and "missing" in m for m in msgs)


@pytest.mark.unit
def test_backend_cloud_empty_model_returns_none_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S-099: empty ``cloud_model`` → graceful absence + WARNING."""
    caplog.set_level(logging.WARNING, logger="seerflow.llm.factory")
    out = build_llm_backend(
        _cfg(
            backend="cloud",
            cloud_provider="openai",
            cloud_api_key="sk-x",
            cloud_model="",
        )
    )
    assert out is None
    msgs = [r.getMessage() for r in caplog.records]
    assert any("cloud_model" in m and "missing" in m for m in msgs)


@pytest.mark.unit
def test_backend_cloud_anthropic_import_error_returns_none_warns(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S-099: ``anthropic`` SDK missing → graceful absence + install hint."""

    def _raise(**_: Any) -> Any:
        raise ImportError("anthropic SDK not installed (pip install seerflow[llm-cloud])")

    monkeypatch.setattr("seerflow.llm.factory.AnthropicBackend", _raise)
    caplog.set_level(logging.WARNING, logger="seerflow.llm.factory")

    out = build_llm_backend(
        _cfg(
            backend="cloud",
            cloud_provider="anthropic",
            cloud_api_key="sk-x",
            cloud_model="claude-haiku-4-5",
        )
    )
    assert out is None
    msgs = [r.getMessage() for r in caplog.records]
    assert any("anthropic" in m and "not installed" in m for m in msgs)
    assert any("seerflow[llm-cloud]" in m for m in msgs)


@pytest.mark.unit
def test_backend_cloud_openai_import_error_returns_none_warns(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S-099: ``openai`` SDK missing → graceful absence + install hint."""

    def _raise(**_: Any) -> Any:
        raise ImportError("openai SDK not installed (pip install seerflow[llm-cloud])")

    monkeypatch.setattr("seerflow.llm.factory.OpenAIBackend", _raise)
    caplog.set_level(logging.WARNING, logger="seerflow.llm.factory")

    out = build_llm_backend(
        _cfg(
            backend="cloud",
            cloud_provider="openai",
            cloud_api_key="sk-x",
            cloud_model="gpt-4o-mini",
        )
    )
    assert out is None
    msgs = [r.getMessage() for r in caplog.records]
    assert any("openai" in m and "not installed" in m for m in msgs)
    assert any("seerflow[llm-cloud]" in m for m in msgs)


@pytest.mark.unit
def test_llama_cpp_missing_model_path_returns_none_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="seerflow.llm.factory")
    out = build_llm_backend(_cfg(backend="llama_cpp", model_path=""))
    assert out is None
    assert any(
        "model_path missing" in r.getMessage() and r.levelno == logging.WARNING
        for r in caplog.records
    )


@pytest.mark.unit
def test_llama_cpp_nonexistent_path_returns_none_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="seerflow.llm.factory")
    out = build_llm_backend(_cfg(backend="llama_cpp", model_path=str(tmp_path / "missing.gguf")))
    assert out is None
    assert any("missing or not a .gguf" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_llama_cpp_wrong_suffix_returns_none_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "model.bin"
    path.write_bytes(b"junk")
    caplog.set_level(logging.WARNING, logger="seerflow.llm.factory")
    out = build_llm_backend(_cfg(backend="llama_cpp", model_path=str(path)))
    assert out is None
    assert any("missing or not a .gguf" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_llama_cpp_import_error_returns_none_warns(
    gguf_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _raise(**_: Any) -> Any:
        raise ImportError("No module named 'llama_cpp'")

    monkeypatch.setattr("seerflow.llm.factory.LlamaCppBackend", _raise)
    caplog.set_level(logging.WARNING, logger="seerflow.llm.factory")
    out = build_llm_backend(_cfg(backend="llama_cpp", model_path=str(gguf_file)))
    assert out is None
    msgs = [r.getMessage() for r in caplog.records]
    assert any("llama-cpp-python not installed" in m and "seerflow[llm-cpu]" in m for m in msgs)


@pytest.mark.unit
def test_llama_cpp_runtime_error_reraises_and_logs(
    gguf_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _raise(**_: Any) -> Any:
        raise RuntimeError("corrupt GGUF")

    monkeypatch.setattr("seerflow.llm.factory.LlamaCppBackend", _raise)
    caplog.set_level(logging.ERROR, logger="seerflow.llm.factory")
    with pytest.raises(RuntimeError, match="corrupt GGUF"):
        build_llm_backend(_cfg(backend="llama_cpp", model_path=str(gguf_file)))
    assert any(
        r.levelno == logging.ERROR and "backend initialisation failed" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.unit
def test_llama_cpp_happy_path_returns_backend(
    gguf_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = object()
    captured: dict[str, Any] = {}

    def _factory(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("seerflow.llm.factory.LlamaCppBackend", _factory)
    out = build_llm_backend(
        _cfg(
            backend="llama_cpp",
            model_path=str(gguf_file),
            n_ctx=2048,
            n_threads=3,
            n_gpu_layers=1,
            seed=99,
        )
    )
    assert out is sentinel
    assert captured["model_path"] == gguf_file
    assert captured["n_ctx"] == 2048
    assert captured["n_threads"] == 3
    assert captured["n_gpu_layers"] == 1
    assert captured["seed"] == 99


@pytest.mark.unit
def test_explicit_logger_is_used(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the caller passes a logger, factory uses it (not the module default)."""
    custom = logging.getLogger("test.llm.factory.explicit")
    caplog.set_level(logging.INFO, logger="test.llm.factory.explicit")
    build_llm_backend(_cfg(), log=custom)
    assert any(r.name == "test.llm.factory.explicit" for r in caplog.records)
