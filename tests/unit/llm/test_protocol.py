"""Unit tests for ``seerflow.llm.protocol.LLMBackend`` (S-070 Task 1).

The Protocol is decorated ``@runtime_checkable`` so consumers can defensively
``isinstance(x, LLMBackend)``. These tests pin the surface: ``name: str`` +
``async complete(prompt, *, max_tokens, temperature, stop) -> str``.
"""

from __future__ import annotations

import pytest

from seerflow.llm import LLMBackend


class _ValidStub:
    name = "stub"

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
        stop: tuple[str, ...] = (),
    ) -> str:
        return ""


class _NoComplete:
    name = "stub"


class _NoName:
    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
        stop: tuple[str, ...] = (),
    ) -> str:
        return ""


@pytest.mark.unit
def test_valid_stub_satisfies_protocol() -> None:
    assert isinstance(_ValidStub(), LLMBackend)


@pytest.mark.unit
def test_missing_complete_does_not_satisfy_protocol() -> None:
    assert not isinstance(_NoComplete(), LLMBackend)


@pytest.mark.unit
def test_missing_name_does_not_satisfy_protocol() -> None:
    # ``runtime_checkable`` Protocol checks attribute presence; absent ``name``
    # must fail the check.
    assert not isinstance(_NoName(), LLMBackend)


@pytest.mark.unit
def test_protocol_is_runtime_checkable() -> None:
    # The decorator sets ``_is_runtime_protocol = True`` on the class.
    assert getattr(LLMBackend, "_is_runtime_protocol", False) is True
