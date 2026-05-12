"""Config-driven factory for ``LLMBackend`` instances (S-070, S-098).

Graceful absence is the explicit contract: when the operator has not
configured a backend, or has configured one whose optional dependency is
not installed, or has pointed at a missing model file / blank Ollama
URL or model name, the factory returns ``None`` and logs at INFO
(intentional absence) or WARNING (config asked for a backend but it
could not be loaded). Real misconfiguration — typos in the backend name,
corrupted model files — surface immediately.

Three-state health surface (driven from ``build_llm_backend``'s return):

- backend instance + ``cfg.backend`` non-empty → ``"ready"``
- ``None`` + ``cfg.backend == ""``                → ``"disabled"``
- ``None`` + ``cfg.backend != ""``                → ``"degraded"``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from seerflow._config_validation import ConfigError
from seerflow.llm.backends.llama_cpp import LlamaCppBackend
from seerflow.llm.backends.ollama import OllamaBackend

if TYPE_CHECKING:
    from seerflow.config import LLMConfig
    from seerflow.llm.protocol import LLMBackend

_VALID_BACKENDS: frozenset[str] = frozenset({"", "llama_cpp", "ollama", "cloud"})


def _maybe_load_ollama(cfg: LLMConfig, log: logging.Logger) -> LLMBackend | None:
    """Build an ``OllamaBackend`` from config; ``None`` on graceful absence.

    Graceful-absence paths (return ``None`` + WARNING):

    - empty ``ollama_url``
    - empty ``ollama_model``

    No daemon probe is performed here — the first ``complete(...)`` call is
    when Ollama is actually contacted. Health surfaces *configuration*
    readiness, not *runtime* daemon health.
    """
    if not cfg.ollama_url:
        log.warning("llm: ollama_url missing → disabled")
        return None
    if not cfg.ollama_model:
        log.warning("llm: ollama_model missing → disabled")
        return None
    backend = OllamaBackend(
        base_url=cfg.ollama_url,
        model=cfg.ollama_model,
        timeout_s=cfg.ollama_timeout_s,
    )
    log.info(
        "ollama: configured backend url=%s model=%s",
        cfg.ollama_url,
        cfg.ollama_model,
    )
    return backend


def _maybe_load_llama_cpp(cfg: LLMConfig, log: logging.Logger) -> LLMBackend | None:
    """Load ``LlamaCppBackend`` or return ``None`` on graceful-absence paths.

    Factored out so unit tests can monkeypatch this helper (rather than
    monkeypatching the constructor) when exercising the factory's branches.
    """
    if not cfg.model_path:
        log.warning("llm: model_path missing → disabled")
        return None
    path = Path(cfg.model_path)
    if not path.is_file() or path.suffix.lower() != ".gguf":
        log.warning(
            "llm: model_path %s missing or not a .gguf file → disabled",
            cfg.model_path,
        )
        return None
    try:
        return LlamaCppBackend(
            model_path=path,
            n_ctx=cfg.n_ctx,
            n_threads=cfg.n_threads,
            n_gpu_layers=cfg.n_gpu_layers,
            seed=cfg.seed,
        )
    except ImportError:
        log.warning(
            "llm: llama-cpp-python not installed → disabled (pip install seerflow[llm-cpu])"
        )
        return None


def build_llm_backend(cfg: LLMConfig, *, log: logging.Logger | None = None) -> LLMBackend | None:
    """Build an ``LLMBackend`` from config; ``None`` on graceful absence.

    Raises ``ConfigError`` only on a typo'd ``backend`` value. All other
    failure modes (missing optional dep, missing model file, deferred
    backends) return ``None`` with a log line. Real misconfiguration in
    the underlying engine (e.g. corrupt GGUF surfacing as a ``RuntimeError``
    from ``Llama(...)``) is re-raised by ``_maybe_load_llama_cpp`` after
    being logged at ERROR — silent failure on real misconfig is the worst
    possible UX.
    """
    logger = log if log is not None else logging.getLogger(__name__)

    if cfg.backend not in _VALID_BACKENDS:
        raise ConfigError(
            "llm.backend must be one of "
            f"{sorted(b for b in _VALID_BACKENDS if b)}, got {cfg.backend!r}"
        )

    if cfg.backend == "":
        logger.info("llm: disabled (no backend configured)")
        return None

    if cfg.backend == "ollama":
        return _maybe_load_ollama(cfg, logger)

    if cfg.backend == "cloud":
        logger.info("llm: backend=cloud deferred to S-099")
        return None

    # cfg.backend == "llama_cpp"
    try:
        return _maybe_load_llama_cpp(cfg, logger)
    except ImportError:  # pragma: no cover - safety net; the helper swallows ImportError
        logger.warning(
            "llm: llama-cpp-python not installed → disabled (pip install seerflow[llm-cpu])"
        )
        return None
    except Exception:
        # Real misconfiguration (corrupt GGUF, OOM during mmap, etc.).
        # Log + re-raise so the operator sees the failure at boot.
        logger.error("llm: backend initialisation failed", exc_info=True)
        raise
