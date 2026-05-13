"""Unit tests for ``seerflow.llm.rule_suggestion.parser.extract_yaml``.

Covers AC12: fenced YAML extraction from a free-form LLM completion.
"""

from __future__ import annotations

from seerflow.llm.rule_suggestion.parser import extract_yaml


class TestExtractYaml:
    def test_extracts_yaml_lang_fence(self) -> None:
        """AC12: ```` ```yaml ... ``` ```` fence body is returned."""
        text = (
            "Here is the rule:\n"
            "\n"
            "```yaml\n"
            "title: SSH brute force\n"
            "level: high\n"
            "```\n"
            "Hope that helps!"
        )
        assert extract_yaml(text) == "title: SSH brute force\nlevel: high"

    def test_extracts_unlabeled_fence(self) -> None:
        """AC12: ```` ``` ... ``` ```` (no lang tag) also works."""
        text = "```\ntitle: t\n```"
        assert extract_yaml(text) == "title: t"

    def test_first_fence_wins(self) -> None:
        """AC12: only the first fence body is returned."""
        text = "```yaml\ntitle: First\n```\nand another\n```yaml\ntitle: Second\n```\n"
        assert extract_yaml(text) == "title: First"

    def test_no_fence_returns_stripped_whole(self) -> None:
        """AC12: no fence → return stripped whole-text."""
        text = "  title: plain\nlevel: low  "
        assert extract_yaml(text) == "title: plain\nlevel: low"

    def test_empty_input_returns_empty_string(self) -> None:
        """AC12: empty input never raises."""
        assert extract_yaml("") == ""
        assert extract_yaml("   \n\t") == ""

    def test_unterminated_fence_falls_back(self) -> None:
        """AC12: a fence without its closing backticks is treated as no fence."""
        text = "```yaml\ntitle: open\n"
        # No closing fence — falls back to stripped whole text.
        assert "title: open" in extract_yaml(text)

    def test_handles_yml_label(self) -> None:
        """AC12: ``yml`` lang tag is also accepted."""
        text = "```yml\ntitle: t\n```"
        assert extract_yaml(text) == "title: t"

    def test_preserves_inner_whitespace(self) -> None:
        """AC12: inner YAML whitespace is preserved (indentation matters)."""
        text = "```yaml\ndetection:\n  selection:\n    a: b\n  condition: selection\n```"
        result = extract_yaml(text)
        assert "  selection:" in result
        assert "    a: b" in result
