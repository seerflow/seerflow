"""Tests for query CLI utilities — duration parsing, formatting, argparse."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


class TestParseDuration:
    def test_minutes(self) -> None:
        from seerflow.query import parse_duration

        assert parse_duration("30m") == 30 * 60 * 1_000_000_000

    def test_hours(self) -> None:
        from seerflow.query import parse_duration

        assert parse_duration("1h") == 3_600_000_000_000

    def test_days(self) -> None:
        from seerflow.query import parse_duration

        assert parse_duration("7d") == 7 * 24 * 3_600_000_000_000

    def test_multi_digit(self) -> None:
        from seerflow.query import parse_duration

        assert parse_duration("24h") == 24 * 3_600_000_000_000

    def test_invalid_unit(self) -> None:
        from seerflow.query import parse_duration

        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("5x")

    def test_empty_string(self) -> None:
        from seerflow.query import parse_duration

        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("")

    def test_no_number(self) -> None:
        from seerflow.query import parse_duration

        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("h")

    def test_zero(self) -> None:
        from seerflow.query import parse_duration

        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("0h")


class TestFormatTimestamp:
    def test_known_timestamp(self) -> None:
        from seerflow.query import format_timestamp

        result = format_timestamp(1_700_000_000_000_000_000)
        assert "2023" in result or "2024" in result
        assert ":" in result

    def test_format_is_readable(self) -> None:
        from seerflow.query import format_timestamp

        result = format_timestamp(1_700_000_000_000_000_000)
        assert len(result) == 19


class TestFormatTable:
    def test_basic_table(self) -> None:
        from seerflow.query import format_table

        headers = ["NAME", "AGE"]
        rows = [["Alice", "30"], ["Bob", "25"]]
        result = format_table(headers, rows)
        lines = result.strip().split("\n")
        assert len(lines) == 4
        assert "NAME" in lines[0]
        assert "AGE" in lines[0]
        assert "---" in lines[1]
        assert "Alice" in lines[2]
        assert "Bob" in lines[3]

    def test_auto_sizing(self) -> None:
        from seerflow.query import format_table

        headers = ["X", "LONG_HEADER"]
        rows = [["short", "a"], ["very long value here", "b"]]
        result = format_table(headers, rows)
        lines = result.strip().split("\n")
        assert "very long value here" in lines[3]

    def test_empty_rows(self) -> None:
        from seerflow.query import format_table

        headers = ["A", "B"]
        rows: list[list[str]] = []
        result = format_table(headers, rows)
        lines = result.strip().split("\n")
        assert len(lines) == 2

    def test_single_column(self) -> None:
        from seerflow.query import format_table

        headers = ["VALUE"]
        rows = [["hello"], ["world"]]
        result = format_table(headers, rows)
        assert "hello" in result
        assert "world" in result

    def test_empty_headers(self) -> None:
        from seerflow.query import format_table

        assert format_table([], []) == ""


class TestQueryArgparse:
    def test_query_events_last(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "events", "--last", "1h"])
        assert args.command == "query"
        assert args.query_type == "events"
        assert args.last == "1h"

    def test_query_events_template(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "events", "--template", "5"])
        assert args.query_type == "events"
        assert args.template == 5

    def test_query_events_source(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "events", "--source", "syslog"])
        assert args.source == "syslog"

    def test_query_events_json(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "events", "--json"])
        assert args.json is True

    def test_query_events_limit(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "events", "--limit", "20"])
        assert args.limit == 20

    def test_query_events_severity(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "events", "--severity", "3"])
        assert args.severity == 3

    def test_query_alerts_defaults(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "alerts"])
        assert args.command == "query"
        assert args.query_type == "alerts"
        assert args.last is None
        assert args.json is False
        assert args.limit == 50

    def test_query_alerts_type(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "alerts", "--type", "ml"])
        assert args.type == "ml"

    def test_query_alerts_tactic(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "alerts", "--tactic", "discovery"])
        assert args.tactic == "discovery"

    def test_query_alerts_technique(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "alerts", "--technique", "t1033"])
        assert args.technique == "t1033"

    def test_query_alerts_tactic_default_none(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "alerts"])
        assert args.tactic is None
        assert args.technique is None

    def test_query_templates_defaults(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "templates"])
        assert args.command == "query"
        assert args.query_type == "templates"
        assert args.limit == 50

    def test_query_templates_json(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "templates", "--json"])
        assert args.json is True


class TestRunQueryEvents:
    async def test_events_table_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query events outputs formatted table."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.models.event import SeerflowEvent, SeverityLevel
        from seerflow.query import run_query_events
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.ERROR,
            message="test error message for query",
            source_type="syslog",
            source_id="test",
            template_id=5,
        )
        await storage.write_events([event])
        await storage.flush()

        args = argparse.Namespace(
            last=None, template=None, source=None, severity=None, limit=50, json=False
        )
        await run_query_events(storage, args)
        captured = capsys.readouterr()

        assert "TIMESTAMP" in captured.out
        assert "ERROR" in captured.out
        assert "syslog" in captured.out
        assert "test error message" in captured.out

        await storage.close()

    async def test_events_json_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query events with --json outputs valid JSON."""
        import argparse
        import json

        from seerflow.config import StorageConfig
        from seerflow.models.event import SeerflowEvent
        from seerflow.query import run_query_events
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            message="json test",
            source_type="file",
        )
        await storage.write_events([event])
        await storage.flush()

        args = argparse.Namespace(
            last=None, template=None, source=None, severity=None, limit=50, json=True
        )
        await run_query_events(storage, args)
        captured = capsys.readouterr()

        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

        await storage.close()

    async def test_events_with_last_filter(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query events with --last filter uses time range."""
        import argparse
        import time

        from seerflow.config import StorageConfig
        from seerflow.models.event import SeerflowEvent
        from seerflow.query import run_query_events
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=time.time_ns(),
            observed_ns=time.time_ns(),
            message="recent event",
            source_type="syslog",
        )
        await storage.write_events([event])
        await storage.flush()

        args = argparse.Namespace(
            last="1h", template=None, source=None, severity=None, limit=50, json=False
        )
        await run_query_events(storage, args)
        captured = capsys.readouterr()
        assert "recent event" in captured.out

        await storage.close()

    async def test_events_no_results(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query events with no results prints message."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.query import run_query_events
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        args = argparse.Namespace(
            last=None, template=None, source=None, severity=None, limit=50, json=False
        )
        await run_query_events(storage, args)
        captured = capsys.readouterr()
        assert "No events found" in captured.out

        await storage.close()


class TestRunQueryAlerts:
    async def test_alerts_table_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query alerts outputs formatted table."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        alert = Alert(
            alert_id="alert-001",
            alert_type="ml",
            timestamp_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.ERROR,
            rule_name="hst-anomaly",
            description="Anomaly detected: score=0.850",
            entity_uuid="ent-1",
            entity_value="192.168.1.1",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            risk_score=0.85,
            dedup_key="hst:5:syslog",
        )
        await storage.write_alert(alert)

        args = argparse.Namespace(
            last=None, type=None, severity=None, limit=50, json=False, tactic=None, technique=None
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()

        assert "TIMESTAMP" in captured.out
        assert "ml" in captured.out
        assert "hst-anomaly" in captured.out
        assert "0.850" in captured.out

        await storage.close()

    async def test_alerts_with_last_filter(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query alerts with --last filter uses time range."""
        import argparse
        import time

        from seerflow.config import StorageConfig
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        alert = Alert(
            alert_id="alert-recent",
            alert_type="ml",
            timestamp_ns=time.time_ns(),
            severity_id=SeverityLevel.WARNING,
            rule_name="hst-anomaly",
            description="recent alert",
            entity_uuid="ent-1",
            entity_value="10.0.0.1",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            risk_score=0.75,
            dedup_key="hst:1:syslog-recent",
        )
        await storage.write_alert(alert)

        args = argparse.Namespace(
            last="1h", type=None, severity=None, limit=50, json=False, tactic=None, technique=None
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()
        assert "hst-anomaly" in captured.out
        assert "1 alert(s) total" in captured.out

        await storage.close()

    async def test_alerts_json_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query alerts with --json outputs valid JSON."""
        import argparse
        import json

        from seerflow.config import StorageConfig
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        alert = Alert(
            alert_id="alert-json",
            alert_type="ml",
            timestamp_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.ERROR,
            rule_name="hst-anomaly",
            description="json alert test",
            entity_uuid="ent-1",
            entity_value="10.0.0.1",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            risk_score=0.90,
            dedup_key="hst:1:syslog-json",
        )
        await storage.write_alert(alert)

        args = argparse.Namespace(
            last=None, type=None, severity=None, limit=50, json=True, tactic=None, technique=None
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["type"] == "ml"

        await storage.close()

    async def test_alerts_no_results(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query alerts with no results prints message."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        args = argparse.Namespace(
            last=None, type=None, severity=None, limit=50, json=False, tactic=None, technique=None
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()
        assert "No alerts found" in captured.out

        await storage.close()

    async def test_alerts_table_shows_tactics_and_techniques(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Alert table output includes TACTICS and TECHNIQUES columns."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        alert = Alert(
            alert_id="alert-tactic",
            alert_type="sigma",
            timestamp_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="recon-rule",
            description="Discovery detected",
            entity_uuid="ent-1",
            entity_value="10.0.0.1",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            mitre_tactics=("discovery",),
            mitre_techniques=("t1033",),
            risk_score=0.70,
            dedup_key="sigma:recon",
        )
        await storage.write_alert(alert)

        args = argparse.Namespace(
            last=None, type=None, severity=None, limit=50, json=False, tactic=None, technique=None
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()

        assert "TACTICS" in captured.out
        assert "TECHNIQUES" in captured.out
        assert "Discovery (TA0007)" in captured.out
        assert "T1033" in captured.out

        await storage.close()

    async def test_alerts_json_includes_tactics_and_techniques(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Alert JSON output includes formatted tactics and techniques."""
        import argparse
        import json

        from seerflow.config import StorageConfig
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        alert = Alert(
            alert_id="alert-json-tactic",
            alert_type="sigma",
            timestamp_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.ERROR,
            rule_name="lateral-rule",
            description="Lateral movement",
            entity_uuid="ent-2",
            entity_value="10.0.0.2",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            mitre_tactics=("lateral_movement",),
            mitre_techniques=("t1021.001",),
            risk_score=0.90,
            dedup_key="sigma:lateral",
        )
        await storage.write_alert(alert)

        args = argparse.Namespace(
            last=None, type=None, severity=None, limit=50, json=True, tactic=None, technique=None
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)

        assert parsed[0]["tactics"] == ["Lateral Movement (TA0008)"]
        assert parsed[0]["techniques"] == ["T1021.001"]

        await storage.close()

    async def test_alerts_tactic_filter(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--tactic filter only returns alerts matching the given tactic."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        alert_disco = Alert(
            alert_id="alert-disco",
            alert_type="sigma",
            timestamp_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="disco-rule",
            description="Discovery alert",
            entity_uuid="ent-1",
            entity_value="10.0.0.1",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            mitre_tactics=("discovery",),
            risk_score=0.60,
            dedup_key="sigma:disco",
        )
        alert_exec = Alert(
            alert_id="alert-exec",
            alert_type="sigma",
            timestamp_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.ERROR,
            rule_name="exec-rule",
            description="Execution alert",
            entity_uuid="ent-2",
            entity_value="10.0.0.2",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            mitre_tactics=("execution",),
            risk_score=0.80,
            dedup_key="sigma:exec",
        )
        await storage.write_alert(alert_disco)
        await storage.write_alert(alert_exec)

        args = argparse.Namespace(
            last=None,
            type=None,
            severity=None,
            limit=50,
            json=False,
            tactic="discovery",
            technique=None,
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()

        assert "disco-rule" in captured.out
        assert "exec-rule" not in captured.out

        await storage.close()

    async def test_alerts_technique_filter(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--technique filter only returns alerts matching the given technique."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        alert_t1033 = Alert(
            alert_id="alert-t1033",
            alert_type="sigma",
            timestamp_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="whoami-rule",
            description="whoami detected",
            entity_uuid="ent-1",
            entity_value="10.0.0.1",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            mitre_techniques=("t1033",),
            risk_score=0.60,
            dedup_key="sigma:t1033",
        )
        alert_other = Alert(
            alert_id="alert-t1059",
            alert_type="sigma",
            timestamp_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.ERROR,
            rule_name="scripting-rule",
            description="scripting detected",
            entity_uuid="ent-2",
            entity_value="10.0.0.2",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            mitre_techniques=("t1059",),
            risk_score=0.80,
            dedup_key="sigma:t1059",
        )
        await storage.write_alert(alert_t1033)
        await storage.write_alert(alert_other)

        args = argparse.Namespace(
            last=None,
            type=None,
            severity=None,
            limit=50,
            json=False,
            tactic=None,
            technique="t1033",
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()

        assert "whoami-rule" in captured.out
        assert "scripting-rule" not in captured.out

        await storage.close()

    async def test_alerts_empty_tactics_shows_dash(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Alert with no tactics/techniques shows '-' in table output."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        alert = Alert(
            alert_id="alert-no-mitre",
            alert_type="ml",
            timestamp_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="hst-anomaly",
            description="Anomaly detected",
            entity_uuid="ent-1",
            entity_value="10.0.0.1",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            risk_score=0.85,
            dedup_key="hst:5:syslog-nomt",
        )
        await storage.write_alert(alert)

        args = argparse.Namespace(
            last=None, type=None, severity=None, limit=50, json=False, tactic=None, technique=None
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()

        # Both TACTICS and TECHNIQUES should show '-' for an alert with no mitre data
        assert "-" in captured.out

        await storage.close()


class TestQueryAlertsTypeFilter:
    """Tests for the --type filter on the query alerts subcommand."""

    def test_parse_alerts_with_type_filter(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "alerts", "--type", "correlation"])
        assert args.type == "correlation"

    def test_parse_alerts_type_default_none(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "alerts"])
        assert args.type is None

    async def test_type_filter_returns_only_matching_alerts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--type filter only returns alerts whose alert_type matches."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        alert_ml = Alert(
            alert_id="alert-ml-type",
            alert_type="ml",
            timestamp_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="hst-anomaly",
            description="ML anomaly detected",
            entity_uuid="ent-1",
            entity_value="10.0.0.1",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            risk_score=0.70,
            dedup_key="ml:type-test",
        )
        alert_corr = Alert(
            alert_id="alert-corr-type",
            alert_type="correlation",
            timestamp_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.ERROR,
            rule_name="corr-rule",
            description="Correlation alert",
            entity_uuid="ent-2",
            entity_value="10.0.0.2",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            risk_score=0.90,
            dedup_key="corr:type-test",
        )
        await storage.write_alert(alert_ml)
        await storage.write_alert(alert_corr)

        args = argparse.Namespace(
            last=None,
            type="correlation",
            severity=None,
            limit=50,
            json=False,
            tactic=None,
            technique=None,
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()

        assert "corr-rule" in captured.out
        assert "hst-anomaly" not in captured.out
        assert "1 alert(s) total" in captured.out

        await storage.close()

    async def test_type_filter_no_match_shows_empty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--type filter with no matching alerts prints 'No alerts found'."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        alert_ml = Alert(
            alert_id="alert-ml-only",
            alert_type="ml",
            timestamp_ns=1_700_000_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="hst-anomaly",
            description="ML alert only",
            entity_uuid="ent-1",
            entity_value="10.0.0.1",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            risk_score=0.70,
            dedup_key="ml:only-test",
        )
        await storage.write_alert(alert_ml)

        args = argparse.Namespace(
            last=None,
            type="sigma",
            severity=None,
            limit=50,
            json=False,
            tactic=None,
            technique=None,
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()

        assert "No alerts found" in captured.out

        await storage.close()


class TestRunQueryTemplates:
    async def test_templates_table_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query templates outputs formatted table."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.query import run_query_templates
        from seerflow.storage.sqlite import SqliteBackend, TemplateInfo

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        templates = [
            TemplateInfo(
                template_id=1,
                template_str="Failed login from <*> user=<*>",
                first_seen_ns=1_700_000_000_000_000_000,
                last_seen_ns=1_700_000_000_000_000_000,
                event_count=42,
            ),
        ]
        await storage.write_templates(templates)

        args = argparse.Namespace(limit=50, json=False)
        await run_query_templates(storage, args)
        captured = capsys.readouterr()

        assert "TID" in captured.out
        assert "42" in captured.out
        assert "Failed login" in captured.out

        await storage.close()

    async def test_templates_json_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query templates with --json outputs valid JSON."""
        import argparse
        import json

        from seerflow.config import StorageConfig
        from seerflow.query import run_query_templates
        from seerflow.storage.sqlite import SqliteBackend, TemplateInfo

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        templates = [
            TemplateInfo(
                template_id=1,
                template_str="Login from <*>",
                first_seen_ns=1_700_000_000_000_000_000,
                last_seen_ns=1_700_000_000_000_000_000,
                event_count=10,
            ),
        ]
        await storage.write_templates(templates)

        args = argparse.Namespace(limit=50, json=True)
        await run_query_templates(storage, args)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["template_id"] == 1

        await storage.close()

    async def test_templates_no_results(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query templates with no results prints message."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.query import run_query_templates
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        args = argparse.Namespace(limit=50, json=False)
        await run_query_templates(storage, args)
        captured = capsys.readouterr()
        assert "No templates found" in captured.out

        await storage.close()


class TestRunQuery:
    async def test_run_query_dispatches_events(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """run_query loads config, connects storage, and dispatches to events."""
        import argparse
        from unittest.mock import patch

        from seerflow.config import SeerflowConfig, StorageConfig

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        config = SeerflowConfig(storage=storage_cfg)

        args = argparse.Namespace(
            config=None,
            query_type="events",
            last=None,
            template=None,
            source=None,
            severity=None,
            limit=50,
            json=False,
        )
        with patch("seerflow.config.load_config", return_value=config):
            from seerflow.query import run_query

            await run_query(args)

        captured = capsys.readouterr()
        assert "No events found" in captured.out

    async def test_run_query_dispatches_alerts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """run_query dispatches to alerts subcommand."""
        import argparse
        from unittest.mock import patch

        from seerflow.config import SeerflowConfig, StorageConfig

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        config = SeerflowConfig(storage=storage_cfg)

        args = argparse.Namespace(
            config=None,
            query_type="alerts",
            last=None,
            type=None,
            severity=None,
            limit=50,
            json=False,
            tactic=None,
            technique=None,
        )
        with patch("seerflow.config.load_config", return_value=config):
            from seerflow.query import run_query

            await run_query(args)

        captured = capsys.readouterr()
        assert "No alerts found" in captured.out

    async def test_run_query_dispatches_templates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """run_query dispatches to templates subcommand."""
        import argparse
        from unittest.mock import patch

        from seerflow.config import SeerflowConfig, StorageConfig

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        config = SeerflowConfig(storage=storage_cfg)

        args = argparse.Namespace(
            config=None,
            query_type="templates",
            limit=50,
            json=False,
        )
        with patch("seerflow.config.load_config", return_value=config):
            from seerflow.query import run_query

            await run_query(args)

        captured = capsys.readouterr()
        assert "No templates found" in captured.out


class TestQueryValidation:
    async def test_invalid_alert_type_prints_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        args = argparse.Namespace(
            last=None,
            type="invalid",
            severity=None,
            limit=50,
            json=False,
            tactic=None,
            technique=None,
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()
        assert "unknown alert type" in captured.err
        await storage.close()

    async def test_invalid_technique_prints_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.query import run_query_alerts
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        args = argparse.Namespace(
            last=None,
            type=None,
            severity=None,
            limit=50,
            json=False,
            tactic=None,
            technique="not-a-technique",
        )
        await run_query_alerts(storage, args)
        captured = capsys.readouterr()
        assert "invalid technique" in captured.err.lower()
        assert "not-a-technique" in captured.err
        assert "No alerts found" not in captured.out
        await storage.close()

    async def test_invalid_severity_prints_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.query import run_query_events
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        args = argparse.Namespace(
            last=None, template=None, source=None, severity=99, limit=50, json=False
        )
        await run_query_events(storage, args)
        captured = capsys.readouterr()
        assert "--severity must be between 0 and 6" in captured.err
        await storage.close()


class TestMainDispatch:
    def test_main_dispatches_query(self) -> None:
        """main() dispatches to run_query for query subcommand."""
        import argparse
        from unittest.mock import patch

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(config=None, command="query", query_type="events")
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.__main__._run_async") as mock_run_async,
        ):
            mock_run_async.return_value = None
            main()
            mock_run_async.assert_called_once()


class TestQueryTimelineArgparse:
    def test_parse_timeline_args(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "timeline", "test-uuid-123"])
        assert args.command == "query"
        assert args.query_type == "timeline"
        assert args.entity_uuid == "test-uuid-123"

    def test_parse_timeline_with_last(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "timeline", "test-uuid", "--last", "1h"])
        assert args.last == "1h"

    def test_parse_timeline_with_source_filter(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "timeline", "test-uuid", "--source", "syslog"])
        assert args.source == "syslog"

    def test_parse_timeline_with_severity(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "timeline", "test-uuid", "--severity", "3"])
        assert args.severity == 3

    def test_parse_timeline_with_limit(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "timeline", "test-uuid", "--limit", "500"])
        assert args.limit == 500

    def test_parse_timeline_default_limit(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "timeline", "test-uuid"])
        assert args.limit == 1000

    def test_parse_timeline_with_json(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "timeline", "test-uuid", "--json"])
        assert args.json is True

    def test_parse_timeline_json_default_false(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(["query", "timeline", "test-uuid"])
        assert args.json is False

    def test_parse_timeline_missing_uuid_exits(self) -> None:
        from seerflow.cli import parse_args

        with pytest.raises(SystemExit) as exc:
            parse_args(["query", "timeline"])
        assert exc.value.code == 2

    def test_parse_timeline_all_options(self) -> None:
        from seerflow.cli import parse_args

        args = parse_args(
            [
                "query",
                "timeline",
                "test-uuid-all",
                "--last",
                "7d",
                "--source",
                "file",
                "--severity",
                "2",
                "--limit",
                "200",
                "--json",
            ]
        )
        assert args.entity_uuid == "test-uuid-all"
        assert args.last == "7d"
        assert args.source == "file"
        assert args.severity == 2
        assert args.limit == 200
        assert args.json is True


class TestRunQueryTimeline:
    async def test_timeline_table_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query timeline outputs formatted table for entity events."""
        import argparse
        import time

        from seerflow.config import StorageConfig
        from seerflow.models.event import SeerflowEvent, SeverityLevel
        from seerflow.query import run_query_timeline
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        entity_uuid = "aaaaaaaa-bbbb-5ccc-dddd-eeeeeeeeeeee"
        now_ns = time.time_ns()
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=now_ns,
            observed_ns=now_ns,
            severity_id=SeverityLevel.ERROR,
            message="timeline test event",
            source_type="syslog",
            source_id="test",
            template_id=5,
            entity_refs=(entity_uuid,),
        )
        await storage.write_events([event])
        await storage.flush()

        args = argparse.Namespace(
            entity_uuid=entity_uuid,
            last="1h",
            source=None,
            severity=None,
            limit=1000,
            json=False,
        )
        await run_query_timeline(storage, args)
        captured = capsys.readouterr()

        assert "TIMESTAMP" in captured.out
        assert "ERROR" in captured.out
        assert "syslog" in captured.out
        assert "timeline test event" in captured.out

        await storage.close()

    async def test_timeline_json_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query timeline with --json outputs valid JSON."""
        import argparse
        import json
        import time

        from seerflow.config import StorageConfig
        from seerflow.models.event import SeerflowEvent, SeverityLevel
        from seerflow.query import run_query_timeline
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        entity_uuid = "aaaaaaaa-bbbb-5ccc-dddd-eeeeeeeeeeee"
        now_ns = time.time_ns()
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=now_ns,
            observed_ns=now_ns,
            severity_id=SeverityLevel.WARNING,
            message="json timeline test",
            source_type="file",
            source_id="test",
            template_id=3,
            entity_refs=(entity_uuid,),
        )
        await storage.write_events([event])
        await storage.flush()

        args = argparse.Namespace(
            entity_uuid=entity_uuid,
            last="1h",
            source=None,
            severity=None,
            limit=1000,
            json=True,
        )
        await run_query_timeline(storage, args)
        captured = capsys.readouterr()

        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["message"] == "json timeline test"

        await storage.close()

    async def test_timeline_no_results(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query timeline with no matching events prints message."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.query import run_query_timeline
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        args = argparse.Namespace(
            entity_uuid="4be0643f-1d98-573b-97cd-ca98a65347dd",
            last="1h",
            source=None,
            severity=None,
            limit=1000,
            json=False,
        )
        await run_query_timeline(storage, args)
        captured = capsys.readouterr()
        assert "No events found" in captured.out

        await storage.close()

    async def test_timeline_invalid_duration(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query timeline with invalid --last prints error."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.query import run_query_timeline
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        args = argparse.Namespace(
            entity_uuid="4be0643f-1d98-573b-97cd-ca98a65347dd",
            last="invalid",
            source=None,
            severity=None,
            limit=1000,
            json=False,
        )
        await run_query_timeline(storage, args)
        captured = capsys.readouterr()
        assert "Invalid duration" in captured.err

        await storage.close()

    async def test_timeline_invalid_severity(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Query timeline with invalid --severity prints error."""
        import argparse

        from seerflow.config import StorageConfig
        from seerflow.query import run_query_timeline
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        args = argparse.Namespace(
            entity_uuid="4be0643f-1d98-573b-97cd-ca98a65347dd",
            last="1h",
            source=None,
            severity=99,
            limit=1000,
            json=False,
        )
        await run_query_timeline(storage, args)
        captured = capsys.readouterr()
        assert "--severity must be between 0 and 6" in captured.err

        await storage.close()

    async def test_timeline_default_window_24h(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When --last is not provided, timeline defaults to 24h window."""
        import argparse
        import time

        from seerflow.config import StorageConfig
        from seerflow.models.event import SeerflowEvent, SeverityLevel
        from seerflow.query import run_query_timeline
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)

        entity_uuid = "aaaaaaaa-bbbb-5ccc-dddd-eeeeeeeeeeee"
        now_ns = time.time_ns()
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=now_ns,
            observed_ns=now_ns,
            severity_id=SeverityLevel.INFORMATIONAL,
            message="default window event",
            source_type="file",
            source_id="test",
            entity_refs=(entity_uuid,),
        )
        await storage.write_events([event])
        await storage.flush()

        args = argparse.Namespace(
            entity_uuid=entity_uuid,
            last=None,
            source=None,
            severity=None,
            limit=1000,
            json=False,
        )
        await run_query_timeline(storage, args)
        captured = capsys.readouterr()
        assert "default window event" in captured.out

        await storage.close()


class TestRunQueryDispatchTimeline:
    async def test_run_query_dispatches_timeline(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """run_query dispatches to timeline subcommand."""
        import argparse
        from unittest.mock import patch

        from seerflow.config import SeerflowConfig, StorageConfig

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        config = SeerflowConfig(storage=storage_cfg)

        args = argparse.Namespace(
            config=None,
            query_type="timeline",
            entity_uuid="4be0643f-1d98-573b-97cd-ca98a65347dd",
            last="1h",
            source=None,
            severity=None,
            limit=1000,
            json=False,
        )
        with patch("seerflow.config.load_config", return_value=config):
            from seerflow.query import run_query

            await run_query(args)

        captured = capsys.readouterr()
        assert "No events found" in captured.out
