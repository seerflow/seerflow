"""Unit tests for seerflow.cli_format.format_table."""

from __future__ import annotations

import pytest

from seerflow.cli_format import format_table


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
