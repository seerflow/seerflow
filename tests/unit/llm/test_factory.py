"""Unit tests for ``build_llm_backend`` (S-070 Task 4).

Covers every branch:

- empty backend → ``None`` + INFO ("disabled")
- llama_cpp + missing path → ``None`` + WARNING
- llama_cpp + non-.gguf path → ``None`` + WARNING
- llama_cpp + ImportError → ``None`` + WARNING with install hint
- llama_cpp + non-ImportError → re-raised + ERROR
- llama_cpp + happy path → backend instance
- ollama → ``None`` + INFO ("deferred")
- cloud → ``None`` + INFO ("deferred")
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
def test_backend_ollama_returns_none_logs_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="seerflow.llm.factory")
    out = build_llm_backend(_cfg(backend="ollama"))
    assert out is None
    assert any("ollama" in r.getMessage() and "deferred" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_backend_cloud_returns_none_logs_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="seerflow.llm.factory")
    out = build_llm_backend(_cfg(backend="cloud"))
    assert out is None
    assert any("cloud" in r.getMessage() and "deferred" in r.getMessage() for r in caplog.records)


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
