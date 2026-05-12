"""Unit tests for the response parser (S-071, Task 3)."""

from __future__ import annotations

import pytest

from seerflow.llm.explanation.parser import parse_response


@pytest.mark.unit
def test_parser_extracts_all_four_sections() -> None:
    text = (
        "SUMMARY: Anomalous login attempt from new IP.\n"
        "RATIONALE: alice typically logs in 09-17 UTC; this fired at 03:14 UTC.\n"
        "EVENTS:\n"
        "- 03:14 ssh failed from 10.0.0.1\n"
        "- 03:15 ssh success from 10.0.0.1\n"
        "NEXT STEPS:\n"
        "- Reset alice's password\n"
        "- Notify SOC\n"
    )
    parsed = parse_response(text)
    assert parsed.summary == "Anomalous login attempt from new IP."
    assert "alice typically" in parsed.anomaly_rationale
    assert parsed.contributing_events == (
        "03:14 ssh failed from 10.0.0.1",
        "03:15 ssh success from 10.0.0.1",
    )
    assert parsed.recommended_next_steps == ("Reset alice's password", "Notify SOC")


@pytest.mark.unit
def test_parser_missing_next_steps_yields_empty_tuple() -> None:
    text = "SUMMARY: x\nRATIONALE: y\nEVENTS:\n- e1\n"
    parsed = parse_response(text)
    assert parsed.summary == "x"
    assert parsed.anomaly_rationale == "y"
    assert parsed.contributing_events == ("e1",)
    assert parsed.recommended_next_steps == ()


@pytest.mark.unit
def test_parser_no_section_headers_falls_back_to_summary() -> None:
    text = "Just a paragraph the model wrote without following format."
    parsed = parse_response(text)
    assert parsed.summary == text.strip()
    assert parsed.anomaly_rationale == ""
    assert parsed.contributing_events == ()
    assert parsed.recommended_next_steps == ()


@pytest.mark.unit
def test_parser_handles_star_bullets() -> None:
    text = "SUMMARY: s\nRATIONALE: r\nEVENTS:\n* event one\n* event two\nNEXT STEPS:\n* step one\n"
    parsed = parse_response(text)
    assert parsed.contributing_events == ("event one", "event two")
    assert parsed.recommended_next_steps == ("step one",)


@pytest.mark.unit
def test_parser_empty_input_returns_empty_fields() -> None:
    parsed = parse_response("")
    assert parsed.summary == ""
    assert parsed.anomaly_rationale == ""
    assert parsed.contributing_events == ()
    assert parsed.recommended_next_steps == ()


@pytest.mark.unit
def test_parser_tolerates_extra_whitespace() -> None:
    text = (
        "\n\nSUMMARY:    Padded summary.   \n\n"
        "  RATIONALE: rationale text  \n"
        "EVENTS:\n  - bullet a  \n  - bullet b\n"
        "NEXT STEPS:\n  -    do thing\n"
    )
    parsed = parse_response(text)
    assert parsed.summary == "Padded summary."
    assert parsed.anomaly_rationale == "rationale text"
    assert parsed.contributing_events == ("bullet a", "bullet b")
    assert parsed.recommended_next_steps == ("do thing",)


@pytest.mark.unit
def test_parser_handles_multiline_rationale_text_without_bullets() -> None:
    text = "SUMMARY: s\nRATIONALE: line1\nline2 continued\nEVENTS:\n- e\n"
    parsed = parse_response(text)
    assert "line1" in parsed.anomaly_rationale
    assert "line2 continued" in parsed.anomaly_rationale
