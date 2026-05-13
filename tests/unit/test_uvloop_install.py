"""Tests for uvloop integration in CLI entry point."""

from __future__ import annotations

import asyncio


def test_uvloop_is_importable() -> None:
    """Verify uvloop is installed as a project dependency."""
    import uvloop

    assert uvloop is not None


def test_uvloop_run_executes_coroutine() -> None:
    """uvloop.run() should execute a coroutine and return its result."""
    import uvloop

    async def _sample() -> int:
        await asyncio.sleep(0)
        return 42

    result = uvloop.run(_sample())
    assert result == 42


def test_run_async_uses_uvloop_when_available() -> None:
    """_run_async should use uvloop.run() on platforms where uvloop is importable."""
    from unittest.mock import MagicMock, patch

    import uvloop

    from seerflow.__main__ import _run_async

    async def _noop() -> None:
        pass

    mock_run = MagicMock(side_effect=uvloop.run)
    with patch("uvloop.run", mock_run):
        _run_async(_noop())

    mock_run.assert_called_once()


def test_run_async_falls_back_to_asyncio_on_import_error() -> None:
    """_run_async should fall back to asyncio.run() when uvloop is not importable."""
    import builtins
    from unittest.mock import MagicMock, patch

    from seerflow.__main__ import _run_async

    async def _noop() -> None:
        pass

    coro = _noop()

    original_import = builtins.__import__

    def _block_uvloop(name: str, *args: object, **kwargs: object) -> object:
        if name == "uvloop":
            raise ImportError("uvloop not available")
        return original_import(name, *args, **kwargs)  # type: ignore[call-overload]

    mock_asyncio_run = MagicMock()
    try:
        with (
            patch("builtins.__import__", side_effect=_block_uvloop),
            patch("seerflow.__main__.asyncio.run", mock_asyncio_run),
        ):
            _run_async(coro)
    finally:
        coro.close()

    mock_asyncio_run.assert_called_once_with(coro)
