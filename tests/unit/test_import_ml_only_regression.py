"""Regression guard (S-303): ``seerflow import`` must remain the fast
ML-only path — ``make_handler(ensemble, storage)`` 2-arg minimal form,
no Sigma / correlation / UEBA / IoC engines. FR-070 / OQ-3.

S-303 added ``seerflow analyze`` as a *distinct* full-stack command and
deliberately did not overload ``import``. This test pins that contract so a
future change cannot silently couple the hot fast-path command to the full
detection stack.
"""

from __future__ import annotations

import inspect

from seerflow import import_cmd


def test_run_import_calls_two_arg_make_handler() -> None:
    src = inspect.getsource(import_cmd.run_import)
    assert "make_handler(ensemble, storage)" in src, (
        "import must use the 2-arg ML-only handler form (S-303 constraint)"
    )
    for engine in ("sigma_holder", "correlation_holder", "ueba_engine", "ioc_matcher"):
        assert engine not in src, f"import must not wire {engine} (stays ML-only)"


def test_import_cmd_does_not_import_assemble_handler() -> None:
    src = inspect.getsource(import_cmd)
    assert "assemble_handler" not in src, "import must not depend on the full-stack assembly seam"
