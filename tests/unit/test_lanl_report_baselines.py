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
# Single source of known values (S-359)
# ---------------------------------------------------------------------------


def test_known_sets_derive_from_schema_literals() -> None:
    """_KNOWN_KINDS / _KNOWN_COMPARISONS are derived from the schema Literals."""
    from typing import get_args

    from seerflow.lanl.report.baselines import _KNOWN_COMPARISONS, _KNOWN_KINDS
    from seerflow.lanl.report.schema import BaselineKind, Comparison

    expected_kinds = frozenset(get_args(BaselineKind))
    expected_comparisons = frozenset(get_args(Comparison))
    assert expected_kinds == _KNOWN_KINDS
    assert expected_comparisons == _KNOWN_COMPARISONS


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
# Shipped baselines.yaml — loads cleanly now that S-358 Task 3 populated the
# published rows with real, cited values (no remaining null placeholder).
# ---------------------------------------------------------------------------


class TestShippedBaselinesYaml:
    def test_shipped_yaml_loads(self) -> None:
        """The packaged baselines.yaml loads with no unresolved placeholders.

        S-358 Task 3 replaced the value=null published placeholder with real,
        cited LANL auth+redteam detection results, so load_baselines() now
        succeeds and yields both project_target and published rows.
        """
        from seerflow.lanl.report.baselines import load_baselines

        baselines = load_baselines()  # default path = packaged baselines.yaml
        assert baselines, "shipped registry must yield at least one baseline"
        kinds = {b.kind for b in baselines}
        assert "project_target" in kinds
        assert "published" in kinds

    def test_shipped_yaml_has_cited_published_auc(self) -> None:
        """At least one published AUC baseline exists with a non-empty source."""
        from seerflow.lanl.report.baselines import load_baselines

        published_auc = [
            b for b in load_baselines() if b.kind == "published" and b.metric == "auc"
        ]
        assert published_auc, "expected >=1 published AUC baseline after Task 3"
        assert all(b.source.strip() for b in published_auc)

    def test_default_path_resolves_to_package_dir(self) -> None:
        """load_baselines() with no args reads from the installed package dir."""
        from pathlib import Path

        import seerflow.lanl.report.baselines as mod

        # The module must expose a _DEFAULT_BASELINES_PATH or similar constant,
        # OR load_baselines must work with no args — verify the file exists.
        pkg_dir = Path(mod.__file__).parent
        yaml_path = pkg_dir / "baselines.yaml"
        assert yaml_path.exists(), f"baselines.yaml not found at {yaml_path}"


# ---------------------------------------------------------------------------
# Malformed-structure rejection paths
# ---------------------------------------------------------------------------


class TestMalformedStructure:
    def test_non_list_top_level_raises(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(tmp_path, "metric: auc\nkind: project_target\n")
        with pytest.raises(ValueError, match="list"):
            load_baselines(yaml_file)

    def test_non_dict_row_raises(self, tmp_path: Path) -> None:
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(tmp_path, "- just a string\n")
        with pytest.raises(ValueError, match="mapping"):
            load_baselines(yaml_file)

    def test_non_string_notes_coerced(self, tmp_path: Path) -> None:
        """A non-string `notes` value is coerced to str rather than rejected."""
        from seerflow.lanl.report.baselines import load_baselines

        yaml_file = _write_yaml(
            tmp_path,
            """\
            - metric: auc
              kind: project_target
              value: 0.5
              comparison: gt
              source: "s"
              notes: 123
            """,
        )
        (b,) = load_baselines(yaml_file)
        assert b.notes == "123"
