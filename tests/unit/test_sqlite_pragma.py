"""Tests for SQLite pragma ordering and content."""

from __future__ import annotations


def test_pragmas_include_page_size() -> None:
    from seerflow.storage.sqlite import _PRAGMAS

    assert any("page_size" in p for p in _PRAGMAS)


def test_page_size_before_journal_mode() -> None:
    from seerflow.storage.sqlite import _PRAGMAS

    page_idx = next(i for i, p in enumerate(_PRAGMAS) if "page_size" in p)
    wal_idx = next(i for i, p in enumerate(_PRAGMAS) if "journal_mode" in p)
    assert page_idx < wal_idx
