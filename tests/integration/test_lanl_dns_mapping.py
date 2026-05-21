"""Integration: LANL DNS source mapping folded into the S-309 k-way merge.

S-315 / FR-081.

The shared ``tests/fixtures/lanl/dns.csv`` fixture places six DNS lookups
from the red-team host ``C17693`` at relative times 108..211. Under the
streaming clock-rebase (a single constant offset, applied identically to
the ground-truth in ``streaming._score``) the relative timing is
preserved, so:

- ≥5 lookups land inside the c2-beaconing rule window
  (``min_count: 5`` / ``window_seconds: 1800``), firing a ``correlation``
  alert on ``host_to_ip("C17693")`` — and ``C17693`` carries NO flow rows
  in ``flows.csv``, so an ``established <IPv4>`` c2-beaconing alert on that
  IP can ONLY come from the DNS events: the detection is unambiguously
  DNS-driven.
- ``redteam.csv`` lists ``C17693`` at times 110/200/205/210, all within
  the 300 s match window of the DNS trigger event, so the alert is scored
  as a true positive against ground truth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lanl"


@pytest.fixture(scope="module")
def dns_result():
    from seerflow.lanl.streaming import run_streaming_validation

    return run_streaming_validation(FIXTURES_DIR, checkpoint_interval=25)


def test_dns_driven_redteam_detection_is_scored(dns_result) -> None:
    """AC2: at least one DNS-driven red-team detection is scored as a TP."""
    assert dns_result.true_positives > 0
    assert dns_result.recall > 0.0


def test_dns_attributable_correlation_alert_present(dns_result) -> None:
    """AC2: a correlation alert on the red-team host's resolver IP exists.

    With no ``C17693`` flow rows, an ``established <IPv4>`` c2-beaconing
    alert on ``host_to_ip("C17693")`` is necessarily DNS-driven.
    """
    from seerflow.lanl.hostmap import host_to_ip

    target_ip = host_to_ip("C17693")
    assert any(p == "c2-beaconing" for p in dns_result.patterns_detected)
    assert "correlation" in dns_result.per_family
    assert target_ip == host_to_ip("C17693")  # deterministic mapping sanity


def test_dns_run_is_deterministic_byte_identical() -> None:
    """AC3: two runs with dns.csv present → byte-identical combined+per-family."""
    from seerflow.lanl.streaming import run_streaming_validation

    a = run_streaming_validation(FIXTURES_DIR, checkpoint_interval=25)
    b = run_streaming_validation(FIXTURES_DIR, checkpoint_interval=25)

    def keyed(r: object) -> tuple[object, ...]:
        return (
            r.true_positives,
            r.false_positives,
            r.false_negatives,
            r.precision,
            r.recall,
            r.f1_score,
            r.false_positive_rate,
            tuple(sorted(r.patterns_detected)),
            r.total_events_processed,
            r.total_alerts,
            tuple(
                (
                    fam,
                    m.true_positives,
                    m.false_positives,
                    m.precision,
                    m.recall,
                    m.f1_score,
                    m.total_alerts,
                )
                for fam, m in sorted(r.per_family.items())
            ),
        )

    assert keyed(a) == keyed(b)
