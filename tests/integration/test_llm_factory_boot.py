"""Boot-level integration for the LLM factory (S-070 Task 5).

Validates the three-state health surface from the perspective of the
factory + ``LLMConfig`` integration, without spinning up the full
``pipeline.run`` async stack (which would require receivers, dashboard,
storage, etc.). The wiring inside ``run.py`` is a thin three-line block
that builds the same ``health_state["llm"]`` value we assert here from
the same ``build_llm_backend`` factory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from seerflow.config import LLMConfig
from seerflow.llm import build_llm_backend
from seerflow.pipeline.run import _derive_llm_health

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from seerflow.llm import LLMBackend


def _derive_health(backend: LLMBackend | None, cfg: LLMConfig) -> str:
    """Mirror of the three-state logic in ``pipeline/run.py`` (S-070)."""
    return _derive_llm_health(backend, cfg.backend)


def test_boot_default_config_marks_llm_disabled() -> None:
    cfg = LLMConfig()
    backend = build_llm_backend(cfg)
    assert backend is None
    assert _derive_health(backend, cfg) == "disabled"


def test_boot_with_llama_cpp_and_extant_model_marks_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "phi4.gguf"
    model_path.write_bytes(b"GGUF")

    sentinel = object()
    monkeypatch.setattr("seerflow.llm.factory.LlamaCppBackend", lambda **_: sentinel)

    cfg = LLMConfig(backend="llama_cpp", model_path=str(model_path))
    backend: Any = build_llm_backend(cfg)
    assert backend is sentinel
    assert _derive_health(backend, cfg) == "ready"


def test_boot_with_missing_model_marks_degraded(tmp_path: Path) -> None:
    cfg = LLMConfig(backend="llama_cpp", model_path=str(tmp_path / "absent.gguf"))
    backend = build_llm_backend(cfg)
    assert backend is None
    assert _derive_health(backend, cfg) == "degraded"


def test_boot_with_missing_optional_dep_marks_degraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "phi4.gguf"
    model_path.write_bytes(b"GGUF")

    def _raise(**_: Any) -> Any:
        raise ImportError("No module named 'llama_cpp'")

    monkeypatch.setattr("seerflow.llm.factory.LlamaCppBackend", _raise)
    cfg = LLMConfig(backend="llama_cpp", model_path=str(model_path))
    backend = build_llm_backend(cfg)
    assert backend is None
    assert _derive_health(backend, cfg) == "degraded"


def test_boot_with_ollama_backend_marks_degraded_until_s098() -> None:
    """``ollama`` is a valid config value but the backend is deferred.

    Operators who set ``backend: ollama`` today get ``degraded`` (their
    intent could not be satisfied) until S-098 lands. The factory must
    not raise, so boot continues serving non-LLM features.
    """
    cfg = LLMConfig(backend="ollama")
    backend = build_llm_backend(cfg)
    assert backend is None
    assert _derive_health(backend, cfg) == "degraded"


def test_boot_with_cloud_backend_marks_degraded_until_s099() -> None:
    cfg = LLMConfig(backend="cloud")
    backend = build_llm_backend(cfg)
    assert backend is None
    assert _derive_health(backend, cfg) == "degraded"
