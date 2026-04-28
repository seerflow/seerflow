from __future__ import annotations

from seerflow.threat_intel.metrics import TAXIIFeedMetrics, TAXIIMetricsRegistry


def test_metrics_default_zero() -> None:
    reg = TAXIIMetricsRegistry()
    snap = reg.snapshot("otx")
    assert snap.polls_ok_total == 0
    assert snap.indicators_seen_total == {}
    assert snap.last_successful_poll_at_ns is None
    assert snap.circuit_open is False


def test_record_success_increments() -> None:
    reg = TAXIIMetricsRegistry()
    reg.record_poll_ok("otx", at_ns=42, indicators_by_type={"ipv4": 5, "domain": 3})
    snap = reg.snapshot("otx")
    assert snap.polls_ok_total == 1
    assert snap.last_successful_poll_at_ns == 42
    assert snap.indicators_seen_total == {"ipv4": 5, "domain": 3}


def test_record_failure_and_truncation() -> None:
    reg = TAXIIMetricsRegistry()
    reg.record_poll_failed("otx", auth=False)
    reg.record_poll_failed("otx", auth=True)
    reg.record_truncated("otx", count=10)
    snap = reg.snapshot("otx")
    assert snap.polls_failed_total == 1
    assert snap.polls_auth_failed_total == 1
    assert snap.indicators_truncated_total == 10


def test_aggregate_view_lists_all_feeds() -> None:
    reg = TAXIIMetricsRegistry()
    reg.record_poll_ok("a", at_ns=1, indicators_by_type={})
    reg.record_poll_ok("b", at_ns=2, indicators_by_type={})
    snap = reg.aggregate()
    assert set(snap.feeds.keys()) == {"a", "b"}


# Keep TAXIIFeedMetrics import in scope (tests don't construct it directly,
# but its presence in the public surface is part of the contract).
_ = TAXIIFeedMetrics
