"""Unit tests for seerflow.lanl.report.baselines (S-358 slice 1).

TDD RED phase — these tests must FAIL before the implementation exists.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test_baselines.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# load_baselines — valid input
# ---------------------------------------------------------------------------


class TestLoadBaselinesValid:
    def test_returns_baseline_list(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines
        from seerflow.lanl.report.schema import Baseline

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: auc
              kind: project_target
              value: 0.0
              comparison: gt
              source: "test source"
            """,
        )
        result = load_baselines(yaml_file)
        assert len(result) == 1
        assert isinstance(result[0], Baseline)

    def test_maps_all_fields(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: false_positive_rate
              kind: project_target
              value: 0.02
              comparison: lte
              source: "PRD 2026-03-17"
              notes: "see §5"
            """,
        )
        (b,) = load_baselines(yaml_file)
        assert b.metric == "false_positive_rate"
        assert b.kind == "project_target"
        assert b.value == pytest.approx(0.02)
        assert b.comparison == "lte"
        assert b.source == "PRD 2026-03-17"
        assert b.notes == "see §5"

    def test_notes_optional_absent(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: auc
              kind: project_target
              value: 0.5
              comparison: gt
              source: "src"
            """,
        )
        (b,) = load_baselines(yaml_file)
        assert b.notes is None

    def test_multiple_rows(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: auc
              kind: project_target
              value: 0.0
              comparison: gt
              source: "s1"
            - metric: precision
              kind: project_target
              value: 0.9
              comparison: gte
              source: "s2"
            """,
        )
        result = load_baselines(yaml_file)
        assert len(result) == 2
        assert result[0].metric == "auc"
        assert result[1].metric == "precision"

    def test_all_known_metrics_accepted(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        known = [
            "precision",
            "recall",
            "f1",
            "auc",
            "false_positive_rate",
            "true_positives",
            "false_positives",
            "false_negatives",
        ]
        rows = "\n".join(
            f"- metric: {m}\n"
            "  kind: project_target\n  value: 1.0\n  comparison: gte\n  source: s\n"
            for m in known
        )
        yaml_file = _write_yaml(tmp_path, rows)
        result = load_baselines(yaml_file)
        assert len(result) == len(known)

    def test_all_valid_comparisons_accepted(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        comparisons = ["lt", "lte", "gt", "gte"]
        rows = "\n".join(
            "- metric: auc\n  kind: project_target\n  value: 0.5\n"
            f"  comparison: {c}\n  source: s\n"
            for c in comparisons
        )
        yaml_file = _write_yaml(tmp_path, rows)
        result = load_baselines(yaml_file)
        assert len(result) == 4

    def test_published_kind_accepted_with_numeric_value(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: auc
              kind: published
              value: 0.95
              comparison: gte
              source: "published paper"
            """,
        )
        (b,) = load_baselines(yaml_file)
        assert b.kind == "published"

    def test_integer_value_accepted(self, tmp_path: Path) -> None:
        """Integer values (e.g., true_positives: 1) must be coerced to float."""
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: true_positives
              kind: project_target
              value: 1
              comparison: gte
              source: "functional-review OQ-2"
            """,
        )
        (b,) = load_baselines(yaml_file)
        assert isinstance(b.value, float)
        assert b.value == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# load_baselines — rejection paths
# ---------------------------------------------------------------------------


class TestLoadBaselinesRejection:
    def test_unknown_metric_raises(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: throughput_eps
              kind: project_target
              value: 1000.0
              comparison: gte
              source: "s"
            """,
        )
        with pytest.raises(ValueError, match="metric"):
            load_baselines(yaml_file)

    def test_bad_kind_raises(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: auc
              kind: internal
              value: 0.9
              comparison: gte
              source: "s"
            """,
        )
        with pytest.raises(ValueError, match="kind"):
            load_baselines(yaml_file)

    def test_bad_comparison_raises(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: auc
              kind: project_target
              value: 0.9
              comparison: eq
              source: "s"
            """,
        )
        with pytest.raises(ValueError, match="comparison"):
            load_baselines(yaml_file)

    def test_null_value_raises(self, tmp_path: Path) -> None:
        """null value must be rejected — this is how the published placeholder guard works."""
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: auc
              kind: published
              value: null
              comparison: gte
              source: "PENDING"
            """,
        )
        with pytest.raises(ValueError, match="value"):
            load_baselines(yaml_file)

    def test_string_value_raises(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: auc
              kind: project_target
              value: "high"
              comparison: gt
              source: "s"
            """,
        )
        with pytest.raises(ValueError, match="value"):
            load_baselines(yaml_file)

    def test_empty_source_raises(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: auc
              kind: project_target
              value: 0.9
              comparison: gt
              source: ""
            """,
        )
        with pytest.raises(ValueError, match="source"):
            load_baselines(yaml_file)

    def test_missing_source_raises(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: auc
              kind: project_target
              value: 0.9
              comparison: gt
            """,
        )
        with pytest.raises(ValueError, match="source"):
            load_baselines(yaml_file)


# ---------------------------------------------------------------------------
# Shipped baselines.yaml — must RAISE due to unresolved published placeholder
# ---------------------------------------------------------------------------


class TestShippedBaselinesYaml:
    def test_shipped_yaml_raises_due_to_published_placeholder(self) -> None:
        """The packaged baselines.yaml has a published row with value=null.

        This is intentional: the registry cannot ship with unresolved published
        baselines. load_baselines() must raise ValueError.

        NOTE: This test flips to a positive assertion (no raise) after
        S-358 Task 3 populates the published rows with real values.
        """
        from seerflow.lanl.report.baselines import load_baselines

        with pytest.raises(ValueError):
            load_baselines()  # default path = packaged baselines.yaml

    def test_default_path_resolves_to_package_dir(self) -> None:
        """load_baselines() with no args reads from the installed package dir."""
        from pathlib import Path

        import seerflow.lanl.report.baselines as mod

        # The module must expose a _DEFAULT_BASELINES_PATH or similar constant,
        # OR load_baselines must work with no args — verify the file exists.
        pkg_dir = Path(mod.__file__).parent
        yaml_path = pkg_dir / "baselines.yaml"
        assert yaml_path.exists(), f"baselines.yaml not found at {yaml_path}"
