"""Tests for DrainParser — template extraction, masking, params."""

from __future__ import annotations

from seerflow.parsing.drain import DrainParser, _extract_params, _mask_tokens


class TestRegexMasking:
    def test_mask_ipv4(self) -> None:
        assert _mask_tokens("from 192.168.1.5 to 10.0.0.1") == "from <IP> to <IP>"

    def test_mask_single_ip(self) -> None:
        assert "<IP>" in _mask_tokens("host 172.16.0.1 connected")

    def test_mask_uuid(self) -> None:
        result = _mask_tokens("request a1b2c3d4-e5f6-7890-abcd-ef1234567890 completed")
        assert "<UUID>" in result
        assert "a1b2c3d4" not in result

    def test_mask_no_match(self) -> None:
        assert _mask_tokens("plain text message") == "plain text message"

    def test_mask_combined(self) -> None:
        result = _mask_tokens("host 10.0.0.1 req 550e8400-e29b-41d4-a716-446655440000")
        assert "<IP>" in result
        assert "<UUID>" in result


class TestDrainParser:
    def test_parse_returns_tuple(self) -> None:
        parser = DrainParser()
        result = parser.parse("Login failed for user admin")
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_parse_template_id_is_int(self) -> None:
        parser = DrainParser()
        tid, _, _ = parser.parse("Login failed for user admin")
        assert isinstance(tid, int)
        assert tid > 0

    def test_parse_template_str(self) -> None:
        parser = DrainParser()
        _, template, _ = parser.parse("Login failed for user admin from 192.168.1.5")
        assert "<*>" in template or "<IP>" in template  # wildcards present

    def test_parse_stable_template_id(self) -> None:
        parser = DrainParser()
        tid1, _, _ = parser.parse("Login failed for user alice from 10.0.0.1")
        tid2, _, _ = parser.parse("Login failed for user bob from 10.0.0.2")
        assert tid1 == tid2  # same pattern -> same ID

    def test_parse_different_patterns(self) -> None:
        parser = DrainParser()
        tid1, _, _ = parser.parse("Login failed for user admin")
        tid2, _, _ = parser.parse("Connection established to database")
        assert tid1 != tid2

    def test_template_count(self) -> None:
        parser = DrainParser()
        parser.parse("pattern A message 1")
        parser.parse("pattern B message 2")
        assert parser.template_count >= 1

    def test_configurable_params(self) -> None:
        parser = DrainParser(sim_th=0.5, depth=5, max_clusters=500)
        tid, _template, _params = parser.parse("test message 123")
        assert tid > 0  # works with custom config


class TestParamExtraction:
    def test_basic_extraction(self) -> None:
        params = _extract_params("Login from <IP>", "Login from <*>")
        assert params == ("<IP>",)

    def test_multiple_params(self) -> None:
        params = _extract_params("user alice host <IP>", "user <*> host <*>")
        assert params == ("alice", "<IP>")

    def test_no_wildcards(self) -> None:
        params = _extract_params("exact match", "exact match")
        assert params == ()

    def test_length_mismatch(self) -> None:
        params = _extract_params("short", "longer template here")
        assert params == ()


class TestExports:
    def test_import(self) -> None:
        import seerflow.parsing as mod

        assert hasattr(mod, "DrainParser")

    def test_all(self) -> None:
        import seerflow.parsing as mod

        assert "DrainParser" in mod.__all__
