"""S-224 (SEE-215): unit tests for the test-only source helpers.

These guard the OSError-immune source-resolution path used by other
unit tests to inspect ``src/seerflow`` symbols without going through
``inspect.getsource`` (which depends on the CPython linecache and
intermittently raises ``OSError: could not get source code`` under
pytest-xdist, devcontainers, and stripped-wheel installs).
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


def test_module_source_text_returns_full_module() -> None:
    from seerflow.pipeline import run as run_mod
    from tests.helpers import module_source_text

    src = module_source_text(run_mod)
    assert "def _run_with_config" in src
    assert "def _install_shutdown_handlers" in src


def test_function_source_text_resolves_method_and_dedents() -> None:
    from seerflow.detection.ensemble import DetectionEnsemble
    from tests.helpers import function_source_text

    src = function_source_text(DetectionEnsemble._load_granular_hw)
    # Dedent leaves the ``async def`` at column 0 so the snippet is a
    # standalone parseable module fragment.
    assert src.startswith("async def _load_granular_hw"), src.splitlines()[0]


def test_function_source_text_raises_for_class_qualname() -> None:
    from seerflow.detection.ensemble import DetectionEnsemble
    from tests.helpers import function_source_text

    with pytest.raises(TypeError, match="resolves to a class"):
        function_source_text(DetectionEnsemble, qualname="DetectionEnsemble")


def test_function_source_text_raises_for_unknown_name() -> None:
    from seerflow.pipeline import run as run_mod
    from tests.helpers import function_source_text

    with pytest.raises(ValueError, match="could not resolve"):
        function_source_text(run_mod._run_with_config, qualname="nonexistent_fn")


def test_function_source_text_rejects_locals_qualname() -> None:
    from seerflow.pipeline import run as run_mod
    from tests.helpers import function_source_text

    with pytest.raises(TypeError, match="nested"):
        function_source_text(run_mod._run_with_config, qualname="outer.<locals>.inner")


def test_function_source_text_rejects_empty_qualname() -> None:
    from seerflow.pipeline import run as run_mod
    from tests.helpers import function_source_text

    with pytest.raises(TypeError, match="empty"):
        function_source_text(run_mod._run_with_config, qualname="")


def test_helpers_survive_inspect_getsource_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from seerflow.pipeline import run as run_mod
    from tests.helpers import function_source_text, module_source_text

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise OSError("could not get source code")

    monkeypatch.setattr(inspect, "getsource", _boom)

    # Both helpers must succeed even when inspect.getsource is broken —
    # this is the whole point of S-224.
    assert "_run_with_config" in module_source_text(run_mod)
    assert "_run_with_config" in function_source_text(run_mod._run_with_config)
