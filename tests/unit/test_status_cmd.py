"""Unit tests for ``seerflow.status_cmd`` — formatting + JSON + exit codes (S-075)."""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from seerflow.status_cmd import (
    EXIT_DEGRADED,
    EXIT_HEALTHY,
    EXIT_UNREACHABLE,
    format_human,
    format_json,
    run_status,
)

if TYPE_CHECKING:
    from pathlib import Path


# ----- Fixtures -------------------------------------------------------------


def _healthy_health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "components": {
            "drain3": "running",
            "storage": "connected",
            "detection": "running",
            "correlation": "running",
            "ueba": "disabled",
        },
        "detection": {"source_count": 3},
        "feedback": {"tp": 4, "fp": 2},
    }


def _healthy_stats() -> dict[str, Any]:
    return {
        "total_events": 6_498_221,
        "total_alerts": 87,
        "alerts_by_severity": {
            "critical": 4,
            "high": 18,
            "medium": 44,
            "low": 21,
        },
        "feedback_stats": {"tp": 4, "fp": 2},
        "uptime_seconds": 7_984.5,
        "event_rate_per_sec": 812.34,
        "total_events_processed": 6_498_221,
        "active_sources": 3,
        "model_count": 12,
        "taxii": None,
        "ioc_matcher": None,
        "ioc_enrichment": None,
    }


def _degraded_health() -> dict[str, Any]:
    h = _healthy_health()
    h["status"] = "degraded"
    h["components"]["storage"] = "degraded"
    return h


@pytest.fixture
def healthy_config(tmp_path: Path) -> Path:
    """Write a minimal YAML config and return its path."""
    cfg = tmp_path / "seerflow.yaml"
    cfg.write_text(
        "dashboard_port: 18080\n"
        "health_bind_address: 127.0.0.1\n"
        f"storage:\n  data_dir: {tmp_path}\n",
        encoding="utf-8",
    )
    return cfg


# ----- format_human ---------------------------------------------------------


class TestFormatHuman:
    def test_includes_status_header(self) -> None:
        out = format_human(_healthy_health(), _healthy_stats())
        assert out.startswith("Status: healthy")

    def test_summary_rows_present(self) -> None:
        out = format_human(_healthy_health(), _healthy_stats())
        # All required fields appear as their own line.
        for row in (
            "uptime",
            "event_rate",
            "total_events",
            "total_alerts",
            "active_sources",
            "model_count",
            "alerts_by_severity",
        ):
            assert row in out, f"expected summary row '{row}' in:\n{out}"

    def test_uptime_human_formatted(self) -> None:
        # 7984.5s = 02h 13m 04s
        out = format_human(_healthy_health(), _healthy_stats())
        assert "02h 13m 04s" in out

    def test_event_rate_two_decimals(self) -> None:
        out = format_human(_healthy_health(), _healthy_stats())
        assert "812.34 events/sec" in out

    def test_thousands_separator_for_counts(self) -> None:
        out = format_human(_healthy_health(), _healthy_stats())
        assert "6,498,221" in out

    def test_components_listed(self) -> None:
        out = format_human(_healthy_health(), _healthy_stats())
        # Each component renders on its own line with state.
        assert "drain3" in out
        assert "storage" in out
        assert "connected" in out
        assert "disabled" in out  # ueba

    def test_components_sorted_alphabetically(self) -> None:
        out = format_human(_healthy_health(), _healthy_stats())
        # 'correlation' (c) precedes 'detection' (d) which precedes 'drain3' (d).
        idx_c = out.index("correlation")
        idx_det = out.index("detection")
        idx_dr = out.index("drain3")
        assert idx_c < idx_det < idx_dr

    def test_severity_row_kv_pairs(self) -> None:
        out = format_human(_healthy_health(), _healthy_stats())
        # Each severity key=value pair appears together.
        assert "critical=4" in out
        assert "high=18" in out
        assert "medium=44" in out
        assert "low=21" in out

    def test_degraded_header_reflects_status(self) -> None:
        out = format_human(_degraded_health(), _healthy_stats())
        assert out.startswith("Status: degraded")


class TestFormatHumanEdgeCases:
    def test_zero_uptime_renders_zero_block(self) -> None:
        stats = _healthy_stats()
        stats["uptime_seconds"] = 0.0
        out = format_human(_healthy_health(), stats)
        assert "00h 00m 00s" in out

    def test_empty_severity_breakdown(self) -> None:
        stats = _healthy_stats()
        stats["alerts_by_severity"] = {}
        out = format_human(_healthy_health(), stats)
        # No severity values — line still renders without crashing.
        assert "alerts_by_severity" in out

    def test_missing_optional_fields(self) -> None:
        """Health doc without ``detection`` / ``feedback`` still renders."""
        h = _healthy_health()
        h.pop("detection", None)
        h.pop("feedback", None)
        out = format_human(h, _healthy_stats())
        assert "Status: healthy" in out

    def test_empty_components(self) -> None:
        h = _healthy_health()
        h["components"] = {}
        out = format_human(h, _healthy_stats())
        assert "components" in out

    def test_uptime_hours_minutes_seconds_formatting(self) -> None:
        stats = _healthy_stats()
        # 3661.5s → 01h 01m 01s
        stats["uptime_seconds"] = 3_661.5
        out = format_human(_healthy_health(), stats)
        assert "01h 01m 01s" in out


# ----- format_json ----------------------------------------------------------


class TestFormatJson:
    def test_returns_valid_json(self) -> None:
        out = format_json(_healthy_health(), _healthy_stats())
        parsed = json.loads(out)
        assert isinstance(parsed, dict)

    def test_status_top_level(self) -> None:
        out = format_json(_healthy_health(), _healthy_stats())
        parsed = json.loads(out)
        assert parsed["status"] == "healthy"

    def test_merges_health_and_stats(self) -> None:
        out = format_json(_healthy_health(), _healthy_stats())
        parsed = json.loads(out)
        # Health fields preserved.
        assert "components" in parsed
        # Stats fields preserved.
        assert parsed["total_events"] == 6_498_221
        assert parsed["model_count"] == 12

    def test_required_fields_present(self) -> None:
        out = format_json(_healthy_health(), _healthy_stats())
        parsed = json.loads(out)
        for field in (
            "status",
            "components",
            "total_events",
            "total_alerts",
            "alerts_by_severity",
            "uptime_seconds",
            "event_rate_per_sec",
            "active_sources",
            "model_count",
        ):
            assert field in parsed, f"required JSON field '{field}' missing"

    def test_degraded_status_propagates(self) -> None:
        out = format_json(_degraded_health(), _healthy_stats())
        parsed = json.loads(out)
        assert parsed["status"] == "degraded"


# ----- run_status -----------------------------------------------------------


def _ns(config: Path, *, json_flag: bool = False, timeout: float = 3.0) -> argparse.Namespace:
    return argparse.Namespace(config=str(config), json=json_flag, timeout=timeout)


class TestRunStatusHealthy:
    async def test_healthy_exit_zero(
        self, healthy_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_fetch(
            host: str, port: int, timeout: float
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            assert host == "127.0.0.1"
            assert port == 18080
            return _healthy_health(), _healthy_stats()

        monkeypatch.setattr("seerflow.status_cmd._fetch", fake_fetch)
        code = await run_status(_ns(healthy_config))
        assert code == EXIT_HEALTHY == 0

    async def test_healthy_human_output(
        self,
        healthy_config: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_fetch(
            host: str, port: int, timeout: float
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            return _healthy_health(), _healthy_stats()

        monkeypatch.setattr("seerflow.status_cmd._fetch", fake_fetch)
        await run_status(_ns(healthy_config))
        out = capsys.readouterr().out
        assert "Status: healthy" in out
        assert "model_count" in out
        assert "12" in out

    async def test_healthy_json_output_is_parseable(
        self,
        healthy_config: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_fetch(
            host: str, port: int, timeout: float
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            return _healthy_health(), _healthy_stats()

        monkeypatch.setattr("seerflow.status_cmd._fetch", fake_fetch)
        await run_status(_ns(healthy_config, json_flag=True))
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["status"] == "healthy"
        assert parsed["model_count"] == 12


class TestRunStatusDegraded:
    async def test_degraded_exit_two(
        self, healthy_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_fetch(
            host: str, port: int, timeout: float
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            return _degraded_health(), _healthy_stats()

        monkeypatch.setattr("seerflow.status_cmd._fetch", fake_fetch)
        code = await run_status(_ns(healthy_config))
        assert code == EXIT_DEGRADED == 2

    async def test_degraded_still_prints_body(
        self,
        healthy_config: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Degraded operators still need the snapshot to triage — body must print."""

        async def fake_fetch(
            host: str, port: int, timeout: float
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            return _degraded_health(), _healthy_stats()

        monkeypatch.setattr("seerflow.status_cmd._fetch", fake_fetch)
        await run_status(_ns(healthy_config))
        out = capsys.readouterr().out
        assert "Status: degraded" in out


class TestRunStatusUnreachable:
    async def test_connection_refused_exit_three(
        self, healthy_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_fetch(
            host: str, port: int, timeout: float
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr("seerflow.status_cmd._fetch", fake_fetch)
        code = await run_status(_ns(healthy_config))
        assert code == EXIT_UNREACHABLE == 3

    async def test_connection_refused_writes_hint_to_stderr(
        self,
        healthy_config: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_fetch(
            host: str, port: int, timeout: float
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr("seerflow.status_cmd._fetch", fake_fetch)
        await run_status(_ns(healthy_config))
        err = capsys.readouterr().err
        assert "cannot reach API" in err
        # Hint mentions the relevant config knobs so the operator can diagnose.
        assert "dashboard_port" in err
        assert "health_bind_address" in err

    async def test_timeout_exit_three(
        self, healthy_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_fetch(
            host: str, port: int, timeout: float
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            raise httpx.ReadTimeout("timed out")

        monkeypatch.setattr("seerflow.status_cmd._fetch", fake_fetch)
        code = await run_status(_ns(healthy_config))
        assert code == EXIT_UNREACHABLE == 3

    async def test_unparseable_body_exit_three(
        self, healthy_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the daemon returns junk, treat as unreachable."""

        async def fake_fetch(
            host: str, port: int, timeout: float
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            raise ValueError("not JSON")

        monkeypatch.setattr("seerflow.status_cmd._fetch", fake_fetch)
        code = await run_status(_ns(healthy_config))
        assert code == EXIT_UNREACHABLE == 3
