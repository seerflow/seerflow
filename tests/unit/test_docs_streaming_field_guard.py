"""S-357: guard the testing-doc §4.3 streaming-result field name.

The §4.3 snippet once printed ``result.throughput_eps``, which does not
exist on :class:`StreamingValidationResult` and raised ``AttributeError``
after a completed run. PR #346 fixed it. This guard stops the bad
attribute from creeping back and keeps the doc snippet in lock-step with
the real dataclass contract.

We do NOT police the unrelated ``benchmark --scorecard`` Performance table
cell ``throughput_eps`` (a real ``BenchmarkResult`` field): the bad form
was always the attribute-access ``result.throughput_eps``, so the
substring check below never matches the bare table cell.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from seerflow.lanl.streaming import StreamingValidationResult

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTING_DOC = PROJECT_ROOT / "documents" / "testing-seerflow-against-lanl.md"


@pytest.fixture(scope="module")
def doc_text() -> str:
    return TESTING_DOC.read_text(encoding="utf-8")


class TestStreamingResultFieldGuard:
    def test_doc_present(self) -> None:
        assert TESTING_DOC.is_file(), f"missing testing doc: {TESTING_DOC}"

    def test_no_nonexistent_throughput_eps_attribute(self, doc_text: str) -> None:
        """`result.throughput_eps` is not a real field — must never appear."""
        assert "result.throughput_eps" not in doc_text, (
            "documents/testing-seerflow-against-lanl.md references the "
            "non-existent attribute `result.throughput_eps`; use "
            "`result.throughput_events_per_s` (see StreamingValidationResult)."
        )

    def test_doc_uses_real_streaming_attribute(self, doc_text: str) -> None:
        """The §4.3 snippet must show the correct attribute access."""
        assert "result.throughput_events_per_s" in doc_text, (
            "documents/testing-seerflow-against-lanl.md §4.3 should print "
            "`result.throughput_events_per_s` from StreamingValidationResult."
        )

    @pytest.mark.parametrize(
        "field_name",
        ["throughput_events_per_s", "mean_event_latency_s"],
    )
    def test_streaming_result_exposes_field(self, field_name: str) -> None:
        """The dataclass contract the doc relies on must hold."""
        assert field_name in StreamingValidationResult.__dataclass_fields__, (
            f"StreamingValidationResult must expose `{field_name}` "
            "(documented in testing-seerflow-against-lanl.md §4.3)."
        )
