"""Unit tests for the outbound syslog sink (S-363/FR-002).

Covers RFC 5424 framing (PRI = facility*8 + severity, VERSION, timestamp,
hostname, app-name, BOM-prefixed MSG), the formatter resolver, and both the
UDP (failures counted) and TCP (errors retried) transports — none of which may
block or raise into the pipeline.
"""

from __future__ import annotations

import json
import re
import uuid
from unittest.mock import MagicMock, patch

import pytest

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_alert(
    *,
    rule_name: str = "hst-anomaly",
    severity: SeverityLevel = SeverityLevel.ERROR,
) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=severity,
        rule_name=rule_name,
        description=f"Test alert: {rule_name}",
        entity_uuid="entity-uuid-001",
        entity_value="10.0.0.1",
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.85,
        dedup_key=f"test:{rule_name}",
    )


_PRI_RE = re.compile(rb"^<(\d{1,3})>1 ")


# ---------------------------------------------------------------------------
# Severity / PRI mapping
# ---------------------------------------------------------------------------


class TestSeverityMapping:
    @pytest.mark.parametrize(
        ("level", "expected"),
        [
            (SeverityLevel.TRACE, 7),
            (SeverityLevel.INFORMATIONAL, 6),
            (SeverityLevel.NOTICE, 5),
            (SeverityLevel.WARNING, 4),
            (SeverityLevel.ERROR, 3),
            (SeverityLevel.CRITICAL, 2),
            (SeverityLevel.FATAL, 1),
        ],
    )
    def test_seerflow_level_maps_to_syslog_severity(
        self, level: SeverityLevel, expected: int
    ) -> None:
        from seerflow.alerting.sinks.syslog import _syslog_severity

        assert _syslog_severity(level) == expected

    @pytest.mark.parametrize(
        ("facility", "level", "expected_pri"),
        [
            (1, SeverityLevel.ERROR, 1 * 8 + 3),  # user.error -> 11
            (0, SeverityLevel.FATAL, 0 * 8 + 1),  # kernel.alert -> 1
            (23, SeverityLevel.TRACE, 23 * 8 + 7),  # local7.debug -> 191
            (16, SeverityLevel.CRITICAL, 16 * 8 + 2),  # local0.critical -> 130
        ],
    )
    def test_pri_is_facility_times_eight_plus_severity(
        self, facility: int, level: SeverityLevel, expected_pri: int
    ) -> None:
        from seerflow.alerting.sinks.syslog import _compute_pri

        assert _compute_pri(facility, _make_alert(severity=level)) == expected_pri


# ---------------------------------------------------------------------------
# Formatter resolver
# ---------------------------------------------------------------------------


class TestRenderMessage:
    def test_cef_formatter_renders_cef_line(self) -> None:
        from seerflow.alerting.sinks.syslog import _render_message

        msg = _render_message(_make_alert(rule_name="r-cef"), "cef")
        assert msg.startswith("CEF:0|Seerflow|Seerflow|")
        assert "r-cef" in msg

    def test_leef_formatter_renders_leef_line(self) -> None:
        from seerflow.alerting.sinks.syslog import _render_message

        msg = _render_message(_make_alert(rule_name="r-leef"), "leef")
        assert msg.startswith("LEEF:2.0|Seerflow|Seerflow|")

    def test_json_formatter_renders_compact_json(self) -> None:
        from seerflow.alerting.sinks.syslog import _render_message

        msg = _render_message(_make_alert(rule_name="r-json"), "json")
        obj = json.loads(msg)
        assert obj["rule_name"] == "r-json"
        # Compact separators: no ", " spacing.
        assert ", " not in msg

    def test_non_line_token_collapses_to_json(self) -> None:
        from seerflow.alerting.sinks.syslog import _render_message

        # slack/teams are dict formatters; for a text sink they collapse to JSON.
        msg = _render_message(_make_alert(rule_name="r-slack"), "slack")
        assert json.loads(msg)["rule_name"] == "r-slack"


# ---------------------------------------------------------------------------
# RFC 5424 frame builder
# ---------------------------------------------------------------------------


class TestBuildFrame:
    def _frame(self, **kwargs: object) -> bytes:
        from seerflow.alerting.sinks.syslog import _build_frame

        defaults: dict[str, object] = {
            "facility": 1,
            "hostname": "host-1",
            "app_name": "seerflow",
            "formatter": "json",
        }
        defaults.update(kwargs)
        return _build_frame(_make_alert(), **defaults)  # type: ignore[arg-type]

    def test_starts_with_correct_pri_and_version(self) -> None:
        frame = self._frame(facility=1)  # user + error(3) -> 11
        match = _PRI_RE.match(frame)
        assert match is not None
        assert int(match.group(1)) == 11

    def test_contains_rfc3339_timestamp(self) -> None:
        frame = self._frame().decode("utf-8")
        # 2023-11-14T...Z (epoch 1_700_000_000s).
        assert re.search(r"2023-11-14T\d{2}:\d{2}:\d{2}(\.\d+)?Z", frame)

    def test_contains_hostname_and_app_name(self) -> None:
        frame = self._frame(hostname="myhost", app_name="myapp").decode("utf-8")
        parts = frame.split(" ")
        # <PRI>VER, TIMESTAMP, HOSTNAME, APP-NAME, PROCID, MSGID, SD, MSG...
        assert parts[2] == "myhost"
        assert parts[3] == "myapp"

    def test_nilvalue_procid_msgid_structured_data(self) -> None:
        frame = self._frame().decode("utf-8")
        parts = frame.split(" ")
        assert parts[4] == "-"  # PROCID
        assert parts[5] == "-"  # MSGID
        assert parts[6] == "-"  # STRUCTURED-DATA

    def test_msg_is_bom_prefixed_utf8(self) -> None:
        frame = self._frame(formatter="json")
        # BOM (EF BB BF) precedes the MSG payload per RFC 5424 §6.4.
        assert b"\xef\xbb\xbf" in frame
        msg = frame.split(b"\xef\xbb\xbf", 1)[1]
        assert json.loads(msg.decode("utf-8"))["entity_value"] == "10.0.0.1"

    def test_msg_carries_cef_payload(self) -> None:
        frame = self._frame(formatter="cef")
        msg = frame.split(b"\xef\xbb\xbf", 1)[1].decode("utf-8")
        assert msg.startswith("CEF:0|Seerflow|Seerflow|")

    def test_msg_carries_leef_payload(self) -> None:
        frame = self._frame(formatter="leef")
        msg = frame.split(b"\xef\xbb\xbf", 1)[1].decode("utf-8")
        assert msg.startswith("LEEF:2.0|Seerflow|Seerflow|")


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_satisfies_delivery_target(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink
        from seerflow.alerting.target import DeliveryTarget

        sink = SyslogSink(host="collector", name="sl", min_severity=3)
        assert isinstance(sink, DeliveryTarget)
        assert sink.name == "sl"
        assert sink.min_severity == 3

    def test_rejects_empty_host(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        with pytest.raises(ValueError, match="host"):
            SyslogSink(host="", name="sl")

    def test_rejects_unknown_transport(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        with pytest.raises(ValueError, match="transport"):
            SyslogSink(host="c", name="sl", transport="carrier-pigeon")

    def test_defaults_host_port_facility(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        sink = SyslogSink(host="c", name="sl")
        assert sink._port == 514
        assert sink._facility == 1
        assert sink._transport == "udp"


# ---------------------------------------------------------------------------
# UDP transport — failures are COUNTED, never raised
# ---------------------------------------------------------------------------


class TestUdpTransport:
    async def test_deliver_sends_single_datagram(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        sock = MagicMock()
        sink = SyslogSink(host="c", port=514, name="sl", transport="udp")
        with patch.object(sink, "_open_udp_socket", return_value=sock):
            await sink.deliver(_make_alert())
        sock.send.assert_called_once()
        sent = sock.send.call_args.args[0]
        assert _PRI_RE.match(sent) is not None
        assert sink.failure_count == 0

    async def test_send_failure_is_counted_not_raised(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        sock = MagicMock()
        sock.send.side_effect = OSError("network down")
        sink = SyslogSink(host="c", name="sl", transport="udp")
        with patch.object(sink, "_open_udp_socket", return_value=sock):
            # Must not raise — a transport failure can never crash the pipeline.
            await sink.deliver(_make_alert())
        assert sink.failure_count == 1

    async def test_socket_open_failure_is_counted_not_raised(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        sink = SyslogSink(host="c", name="sl", transport="udp")
        with patch.object(sink, "_open_udp_socket", side_effect=OSError("no route")):
            await sink.deliver(_make_alert())
        assert sink.failure_count == 1


# ---------------------------------------------------------------------------
# TCP transport — errors RETRIED, persistent failure counted, never raised
# ---------------------------------------------------------------------------


class TestTcpTransport:
    async def test_deliver_sends_octet_counted_frame(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        sock = MagicMock()
        sink = SyslogSink(host="c", port=601, name="sl", transport="tcp")
        with patch.object(sink, "_open_tcp_socket", return_value=sock):
            await sink.deliver(_make_alert())
        sock.sendall.assert_called_once()
        payload = sock.sendall.call_args.args[0]
        # RFC 6587 octet-counting: "<len> <frame>".
        length, _, frame = payload.partition(b" ")
        assert int(length) == len(frame)
        assert _PRI_RE.match(frame) is not None
        assert sink.failure_count == 0

    async def test_transient_error_is_retried_then_succeeds(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        good = MagicMock()
        bad = MagicMock()
        bad.sendall.side_effect = OSError("reset")
        sink = SyslogSink(
            host="c", name="sl", transport="tcp", attempts=3, retry_delays=(0.0, 0.0)
        )
        with patch.object(sink, "_open_tcp_socket", side_effect=[bad, good]):
            await sink.deliver(_make_alert())
        # Reconnected and resent on the second attempt.
        good.sendall.assert_called_once()
        assert sink.failure_count == 0

    async def test_persistent_error_counted_after_exhausting_retries(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        bad = MagicMock()
        bad.sendall.side_effect = OSError("reset")
        sink = SyslogSink(host="c", name="sl", transport="tcp", attempts=2, retry_delays=(0.0,))
        with patch.object(sink, "_open_tcp_socket", return_value=bad):
            # Exhausts retries; failure counted, never raised.
            await sink.deliver(_make_alert())
        assert sink.failure_count == 1
        assert bad.sendall.call_count == 2

    async def test_reuses_persistent_socket_across_deliveries(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        sock = MagicMock()
        sink = SyslogSink(host="c", name="sl", transport="tcp")
        with patch.object(sink, "_open_tcp_socket", return_value=sock) as opener:
            await sink.deliver(_make_alert())
            await sink.deliver(_make_alert())
        # One connection reused for both frames (socket not reopened).
        opener.assert_called_once()
        assert sock.sendall.call_count == 2

    async def test_positive_retry_delay_sleeps_between_attempts(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        good = MagicMock()
        bad = MagicMock()
        bad.sendall.side_effect = OSError("reset")
        sink = SyslogSink(host="c", name="sl", transport="tcp", attempts=3, retry_delays=(0.01,))
        with (
            patch.object(sink, "_open_tcp_socket", side_effect=[bad, good]),
            patch("time.sleep") as mock_sleep,
        ):
            await sink.deliver(_make_alert())
        # A positive delay between the failed and successful attempt is honoured.
        mock_sleep.assert_called_once_with(0.01)
        assert sink.failure_count == 0


# ---------------------------------------------------------------------------
# Digest + lifecycle
# ---------------------------------------------------------------------------


class TestDigestAndLifecycle:
    async def test_deliver_digest_sends_each_alert(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        sock = MagicMock()
        sink = SyslogSink(host="c", name="sl", transport="udp")
        with patch.object(sink, "_open_udp_socket", return_value=sock):
            await sink.deliver_digest([_make_alert(), _make_alert()])
        assert sock.send.call_count == 2

    async def test_deliver_digest_empty_is_noop(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        sink = SyslogSink(host="c", name="sl", transport="udp")
        with patch.object(sink, "_open_udp_socket") as opener:
            await sink.deliver_digest([])
        opener.assert_not_called()

    async def test_close_releases_socket(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        sock = MagicMock()
        sink = SyslogSink(host="c", name="sl", transport="tcp")
        with patch.object(sink, "_open_tcp_socket", return_value=sock):
            await sink.deliver(_make_alert())
        await sink.close()
        sock.close.assert_called_once()

    async def test_close_is_noop_when_never_connected(self) -> None:
        from seerflow.alerting.sinks.syslog import SyslogSink

        sink = SyslogSink(host="c", name="sl", transport="tcp")
        await sink.close()  # safe no-op
