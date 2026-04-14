"""Unit tests for ``seerflow.api.constants`` (S-187)."""

from __future__ import annotations

from seerflow.api import constants


def test_max_alert_scan_value() -> None:
    """``MAX_ALERT_SCAN`` keeps the S-186 row-cap at 10_000."""
    assert constants.MAX_ALERT_SCAN == 10_000


def test_max_alert_scan_is_public_int() -> None:
    """Constant must be an ``int`` (not a tuple / enum) and publicly named."""
    assert isinstance(constants.MAX_ALERT_SCAN, int)
    assert not any(name.startswith("_MAX_ALERT_SCAN") for name in dir(constants))


def test_attack_route_does_not_redefine_scan_cap() -> None:
    """``routes.attack`` must source the cap from ``api.constants``, not redefine it."""
    from seerflow.api.routes import attack

    assert not hasattr(attack, "_MAX_ALERT_SCAN")
