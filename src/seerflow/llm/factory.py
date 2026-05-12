"""Config-driven factory for ``LLMBackend`` instances (S-070, S-098, S-099).

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
from seerflow.llm.backends.cloud import AnthropicBackend, OpenAIBackend
from seerflow.llm.backends.llama_cpp import LlamaCppBackend
from seerflow.llm.backends.ollama import OllamaBackend

if TYPE_CHECKING:
    from seerflow.config import LLMConfig
    from seerflow.llm.protocol import LLMBackend

_VALID_BACKENDS: frozenset[str] = frozenset({"", "llama_cpp", "ollama", "cloud"})

# S-099: known cloud providers. Empty / unknown surfaces as graceful absence
# from ``_maybe_load_cloud`` (the config validator already rejects truly
# unknown values; this is defence-in-depth).
_VALID_CLOUD_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai"})


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


def _maybe_load_cloud(cfg: LLMConfig, log: logging.Logger) -> LLMBackend | None:
    """Build a cloud ``LLMBackend`` from config; ``None`` on graceful absence.

    Graceful-absence paths (return ``None`` + WARNING):

    - empty ``cloud_provider``
    - ``cloud_provider`` outside ``{"anthropic", "openai"}`` (defence in depth;
      the config validator already rejects unknown values)
    - empty ``cloud_api_key``
    - empty ``cloud_model``
    - SDK ``ImportError`` (optional dep ``seerflow[llm-cloud]`` not installed)

    No network call is performed here — the SDK client constructor itself
    is lazy (the official Anthropic / OpenAI clients only open sockets on
    the first method call). Health surfaces *configuration* readiness, not
    *runtime* API health.
    """
    provider = cfg.cloud_provider
    if not provider:
        log.warning("llm: cloud_provider missing → disabled")
        return None
    if provider not in _VALID_CLOUD_PROVIDERS:
        log.warning(
            "llm: cloud_provider %r is not one of %s → disabled",
            provider,
            sorted(_VALID_CLOUD_PROVIDERS),
        )
        return None
    if not cfg.cloud_api_key:
        log.warning("llm: cloud_api_key missing → disabled")
        return None
    if not cfg.cloud_model:
        log.warning("llm: cloud_model missing → disabled")
        return None

    base_url = cfg.cloud_base_url or None
    try:
        if provider == "anthropic":
            backend: LLMBackend = AnthropicBackend(
                api_key=cfg.cloud_api_key,
                model=cfg.cloud_model,
                timeout_s=cfg.cloud_timeout_s,
                base_url=base_url,
            )
        else:  # provider == "openai"
            backend = OpenAIBackend(
                api_key=cfg.cloud_api_key,
                model=cfg.cloud_model,
                timeout_s=cfg.cloud_timeout_s,
                base_url=base_url,
            )
    except ImportError:
        log.warning(
            "llm: %s SDK not installed → disabled (pip install seerflow[llm-cloud])",
            provider,
        )
        return None

    # INFO log carries provider + model + (when set) base_url ONLY. The API
    # key MUST NEVER appear in any log line.
    if base_url:
        log.info(
            "cloud: configured backend provider=%s model=%s base_url=%s",
            provider,
            cfg.cloud_model,
            base_url,
        )
    else:
        log.info(
            "cloud: configured backend provider=%s model=%s",
            provider,
            cfg.cloud_model,
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
        return _maybe_load_cloud(cfg, logger)

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
