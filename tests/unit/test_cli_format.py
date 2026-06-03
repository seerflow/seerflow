"""Unit tests for seerflow.cli_format.format_table and emit_doc."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from seerflow.cli_format import emit_doc, format_table

if TYPE_CHECKING:
    import pytest


def test_format_table_pads_columns_to_widest_cell() -> None:
    out = format_table(["NAME", "VAL"], [["a", "1"], ["longer", "22"]])
    assert out == "NAME    VAL\n------  ---\na       1  \nlonger  22 \n"


def test_format_table_returns_empty_string_for_no_headers() -> None:
    assert format_table([], [["a"]]) == ""


def test_format_table_pads_short_rows_with_empty_cells() -> None:
    out = format_table(["A", "B", "C"], [["x"]])
    assert "x" in out
    assert out.splitlines()[0].startswith("A  B  C")


def test_format_table_handles_empty_rows() -> None:
    out = format_table(["NAME"], [])
    assert out == "NAME\n----\n"


def test_emit_doc_json_emits_valid_json_with_trailing_newline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_doc({"a": 1, "b": "x"}, as_json=True)
    out = capsys.readouterr().out
    assert out.endswith("\n")
    assert not out.endswith("\n\n")
    assert json.loads(out) == {"a": 1, "b": "x"}


def test_emit_doc_table_matches_format_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_doc({"metric": "value-ish", "n": 3}, as_json=False)
    out = capsys.readouterr().out
    expected = format_table(["metric", "value"], [["metric", "value-ish"], ["n", "3"]]) + "\n"
    assert out == expected


def test_emit_doc_json_empty_doc(capsys: pytest.CaptureFixture[str]) -> None:
    emit_doc({}, as_json=True)
    assert capsys.readouterr().out == "{}\n"


def test_emit_doc_table_empty_doc(capsys: pytest.CaptureFixture[str]) -> None:
    emit_doc({}, as_json=False)
    assert capsys.readouterr().out == format_table(["metric", "value"], []) + "\n"


def test_emit_doc_table_stringifies_nested_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_doc({"items": [1, 2]}, as_json=False)
    assert "[1, 2]" in capsys.readouterr().out
