"""Tests for the Pipeline builder and consumer loop."""

from __future__ import annotations

import os
import tempfile

from seerflow.config import ReceiverConfig, SeerflowConfig, WebhookEndpointConfig
from seerflow.pipeline import build_pipeline
from seerflow.receivers.base import RawEvent


class TestPipelineBuilder:
    async def test_build_no_receivers(self) -> None:
        config = SeerflowConfig(
            receivers=ReceiverConfig(
                syslog_enabled=False,
                otlp_grpc_enabled=False,
                otlp_http_enabled=False,
                webhook_enabled=False,
            )
        )
        pipeline = await build_pipeline(config)
        assert len(pipeline.manager._receivers) == 0
        await pipeline.stop()

    async def test_build_syslog_only(self) -> None:
        config = SeerflowConfig(
            receivers=ReceiverConfig(
                syslog_enabled=True,
                syslog_udp_port=0,
                syslog_tcp_port=0,
                otlp_grpc_enabled=False,
                otlp_http_enabled=False,
                webhook_enabled=False,
            )
        )
        pipeline = await build_pipeline(config)
        assert "syslog" in pipeline.manager._receivers
        await pipeline.stop()

    async def test_consumer_loop_processes_and_stops(self) -> None:
        config = SeerflowConfig(
            receivers=ReceiverConfig(
                syslog_enabled=False,
                otlp_grpc_enabled=False,
                otlp_http_enabled=False,
                webhook_enabled=False,
            )
        )
        pipeline = await build_pipeline(config)
        # Inject event directly
        event = RawEvent(
            data=b"test", source_type="mock", source_id="m", received_ns=1, metadata={}
        )
        await pipeline.manager.put_event(event)

        processed: list[RawEvent] = []

        async def handler(e: RawEvent) -> None:
            processed.append(e)
            await pipeline.stop()  # stop after first event

        await pipeline.run(handler)
        assert len(processed) == 1
        assert processed[0].data == b"test"

    async def test_pipeline_properties(self) -> None:
        config = SeerflowConfig(
            receivers=ReceiverConfig(
                syslog_enabled=False,
                otlp_grpc_enabled=False,
                otlp_http_enabled=False,
                webhook_enabled=False,
            )
        )
        pipeline = await build_pipeline(config)
        assert pipeline.manager is not None
        assert pipeline.config is config
        await pipeline.stop()


class TestAutoEnable:
    """Tests for auto-enabling receivers from config presence."""

    async def test_webhooks_auto_enables_webhook_receiver(self) -> None:
        """Webhook receiver registers when webhooks non-empty, even if disabled."""
        config = SeerflowConfig(
            receivers=ReceiverConfig(
                syslog_enabled=False,
                otlp_grpc_enabled=False,
                otlp_http_enabled=False,
                webhook_enabled=False,
                webhooks=(WebhookEndpointConfig(path="/hook"),),
            ),
        )
        pipeline = await build_pipeline(config)
        assert "webhook" in pipeline.manager._receivers
        await pipeline.stop()

    async def test_empty_webhooks_no_receiver(self) -> None:
        """No webhook receiver when webhooks list is empty."""
        config = SeerflowConfig(
            receivers=ReceiverConfig(
                syslog_enabled=False,
                otlp_grpc_enabled=False,
                otlp_http_enabled=False,
                webhook_enabled=False,
            ),
        )
        pipeline = await build_pipeline(config)
        assert "webhook" not in pipeline.manager._receivers
        await pipeline.stop()

    async def test_file_paths_auto_enables_file_receiver(self) -> None:
        """File receiver registers when file_paths is non-empty (regression)."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            f.write(b"test\n")
            tmp_path = f.name
        try:
            config = SeerflowConfig(
                receivers=ReceiverConfig(
                    syslog_enabled=False,
                    otlp_grpc_enabled=False,
                    otlp_http_enabled=False,
                    webhook_enabled=False,
                    file_paths=(tmp_path,),
                ),
            )
            pipeline = await build_pipeline(config)
            assert "file" in pipeline.manager._receivers
            await pipeline.stop()
        finally:
            os.unlink(tmp_path)
