"""Integration test: OTLP export to a mock HTTP collector."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import pytest
from aiohttp import web

if TYPE_CHECKING:
    import pathlib

from seerflow.alerting.sinks.otlp import OtlpSink
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


def _make_alert(*, rule_name: str = "hst-anomaly") -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.ERROR,
        rule_name=rule_name,
        description=f"Integration test alert: {rule_name}",
        entity_uuid="entity-uuid-001",
        entity_value="10.0.0.1",
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.9,
        dedup_key=f"test:{rule_name}",
    )


class TestOtlpHttpIntegration:
    @pytest.mark.asyncio
    async def test_export_to_mock_collector(self) -> None:
        """Start a mock OTLP HTTP collector, export alerts, verify receipt."""
        from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
            ExportLogsServiceRequest,
        )

        received: list[ExportLogsServiceRequest] = []

        async def handle_logs(request: web.Request) -> web.Response:
            body = await request.read()
            req = ExportLogsServiceRequest()
            req.ParseFromString(body)
            received.append(req)
            return web.Response(status=200)

        app = web.Application()
        app.router.add_post("/v1/logs", handle_logs)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()

        # Get the actual port assigned
        port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        endpoint = f"http://127.0.0.1:{port}"

        try:
            sink = OtlpSink(
                endpoint=endpoint,
                protocol="http",
                export_interval=1,
            )
            task = asyncio.create_task(sink.run())

            # Enqueue 3 alerts
            for i in range(3):
                sink.enqueue(_make_alert(rule_name=f"rule-{i}"))

            # Wait for flush
            await asyncio.sleep(2.0)

            await sink.stop()
            await asyncio.wait_for(task, timeout=5.0)
            await sink.close()

            # Verify at least one batch received
            assert len(received) >= 1
            total_records = sum(
                len(rl.scope_logs[0].log_records) for req in received for rl in req.resource_logs
            )
            assert total_records == 3

            # Verify content
            first_req = received[0]
            resource = first_req.resource_logs[0].resource
            resource_attrs = {a.key: a.value.string_value for a in resource.attributes}
            assert resource_attrs["service.name"] == "seerflow"

            first_record = first_req.resource_logs[0].scope_logs[0].log_records[0]
            assert first_record.severity_number == 17  # ERROR
            assert first_record.severity_text == "ERROR"
            attrs = {a.key: a.value for a in first_record.attributes}
            assert attrs["entity.type"].string_value == "ip"
        finally:
            await runner.cleanup()


class TestOtlpTlsConfigPropagation:
    """SEE-191: verify otlp_tls YAML propagates all the way to OtlpSink._use_tls."""

    def test_yaml_otlp_tls_true_propagates_to_sink(self, tmp_path: pathlib.Path) -> None:
        from seerflow.config import load_config

        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            'alerting:\n  otlp_endpoint: "host:4317"\n  otlp_protocol: "grpc"\n  otlp_tls: true\n'
        )
        config = load_config(str(yaml_file))
        assert config.alerting.otlp_tls is True

        sink = OtlpSink(
            endpoint=config.alerting.otlp_endpoint,
            protocol=config.alerting.otlp_protocol,
            export_interval=config.alerting.otlp_export_interval_seconds,
            tls=config.alerting.otlp_tls,
        )
        assert sink._use_tls is True

    def test_yaml_omitted_otlp_tls_defaults_to_auto_detect(self, tmp_path: pathlib.Path) -> None:
        from seerflow.config import load_config

        yaml_file = tmp_path / "seerflow.yaml"
        yaml_file.write_text(
            "alerting:\n"
            '  otlp_endpoint: "https://collector.example.com:4317"\n'
            '  otlp_protocol: "grpc"\n'
        )
        config = load_config(str(yaml_file))
        assert config.alerting.otlp_tls is None

        sink = OtlpSink(
            endpoint=config.alerting.otlp_endpoint,
            protocol=config.alerting.otlp_protocol,
            tls=config.alerting.otlp_tls,
        )
        # Auto-detect from https:// scheme → TLS on.
        assert sink._use_tls is True
