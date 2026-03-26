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


class TestPipelineHandlerError:
    """Test the handler exception path (lines 46-47)."""

    async def test_handler_exception_logged_and_continues(self) -> None:
        """When handler raises, pipeline logs error and processes next event."""
        config = SeerflowConfig(
            receivers=ReceiverConfig(
                syslog_enabled=False,
                otlp_grpc_enabled=False,
                otlp_http_enabled=False,
                webhook_enabled=False,
            )
        )
        pipeline = await build_pipeline(config)
        # Inject two events
        ev1 = RawEvent(
            data=b"bad", source_type="mock", source_id="m", received_ns=1, metadata={}
        )
        ev2 = RawEvent(
            data=b"good", source_type="mock", source_id="m", received_ns=2, metadata={}
        )
        await pipeline.manager.put_event(ev1)
        await pipeline.manager.put_event(ev2)

        processed: list[RawEvent] = []
        call_count = 0

        async def handler(e: RawEvent) -> None:
            nonlocal call_count
            call_count += 1
            if e.data == b"bad":
                msg = "deliberate test error"
                raise ValueError(msg)
            processed.append(e)
            await pipeline.stop()

        await pipeline.run(handler)
        assert call_count == 2
        assert len(processed) == 1
        assert processed[0].data == b"good"


class TestBuildPipelineFailures:
    """Test partial/total receiver start failure paths (lines 142-147)."""

    async def test_partial_failure_continues(self) -> None:
        """When one receiver fails to start, pipeline continues with others."""
        from unittest.mock import AsyncMock

        from seerflow.receivers.manager import ReceiverManager

        mgr = ReceiverManager()
        # Register a good receiver (mock)
        good_receiver = AsyncMock()
        good_receiver.start = AsyncMock()
        good_receiver.stop = AsyncMock()
        good_receiver.is_healthy = lambda: True
        mgr.register("good", good_receiver)

        # Register a bad receiver that fails on start
        bad_receiver = AsyncMock()
        bad_receiver.start = AsyncMock(side_effect=OSError("bind failed"))
        bad_receiver.stop = AsyncMock()
        mgr.register("bad", bad_receiver)

        failed = await mgr.start()
        assert "bad" in failed
        assert "good" not in failed

    async def test_all_receivers_fail_raises(self) -> None:
        """When all receivers fail to start, build_pipeline raises RuntimeError."""
        from unittest.mock import AsyncMock, patch

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
        # Patch ReceiverManager.start to simulate all failing
        with patch.object(
            __import__("seerflow.receivers.manager", fromlist=["ReceiverManager"]).ReceiverManager,
            "start",
            new_callable=AsyncMock,
            return_value=["syslog"],
        ):
            import pytest

            with pytest.raises(RuntimeError, match="All receivers failed to start"):
                await build_pipeline(config)
