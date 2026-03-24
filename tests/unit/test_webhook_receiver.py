"""Tests for WebhookReceiver — generic HTTP POST ingestion with field mapping."""

from __future__ import annotations

import json

import aiohttp

from seerflow.receivers.base import Receiver
from seerflow.receivers.manager import ReceiverManager
from seerflow.receivers.webhook import WebhookConfig, WebhookReceiver


class TestWebhookReceiverProtocol:
    def test_isinstance_receiver(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        assert isinstance(receiver, Receiver)


class TestWebhookReceiverLifecycle:
    async def test_start_stop_lifecycle(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        assert not receiver.is_healthy()
        await receiver.start()
        assert receiver.is_healthy()
        await receiver.stop()
        assert not receiver.is_healthy()


class TestWebhookReceiverIngest:
    async def test_receive_json(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            payload = {"message": "hello world", "level": "info"}
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json=payload,
                )
                assert resp.status == 200
            assert mgr.queue_depth == 1
            event = await mgr.get_event()
            assert event.source_type == "webhook"
            assert event.source_id == "webhook"
            assert isinstance(event.data, bytes)
            parsed = json.loads(event.data)
            assert parsed["message"] == "hello world"
            assert event.received_ns > 0
        finally:
            await receiver.stop()

    async def test_receive_form_encoded(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            form_data = {"message": "form hello", "severity": "warn"}
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    data=form_data,
                )
                assert resp.status == 200
            assert mgr.queue_depth == 1
            event = await mgr.get_event()
            assert event.source_type == "webhook"
            parsed = json.loads(event.data)
            assert parsed["message"] == "form hello"
        finally:
            await receiver.stop()

    async def test_field_mapping(self) -> None:
        config = WebhookConfig(
            field_mapping={"severity": "level", "msg": "message"},
            source_id="mapped-webhook",
        )
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, configs=(config,), port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            payload = {"message": "mapped msg", "level": "error"}
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json=payload,
                )
                assert resp.status == 200
            event = await mgr.get_event()
            assert event.metadata["severity"] == "error"
            assert event.metadata["msg"] == "mapped msg"
            assert event.source_id == "mapped-webhook"
        finally:
            await receiver.stop()

    async def test_nested_field_mapping(self) -> None:
        config = WebhookConfig(
            field_mapping={"body_text": "body.text", "host": "meta.host"},
        )
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, configs=(config,), port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            payload = {
                "body": {"text": "nested content"},
                "meta": {"host": "srv-01"},
            }
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json=payload,
                )
                assert resp.status == 200
            event = await mgr.get_event()
            assert event.metadata["body_text"] == "nested content"
            assert event.metadata["host"] == "srv-01"
        finally:
            await receiver.stop()


class TestWebhookReceiverAuth:
    async def test_secret_auth_valid(self) -> None:
        config = WebhookConfig(
            secret_header="X-Webhook-Secret",
            secret_value="my-secret-token",
        )
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, configs=(config,), port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json={"msg": "authed"},
                    headers={"X-Webhook-Secret": "my-secret-token"},
                )
                assert resp.status == 200
            assert mgr.queue_depth == 1
        finally:
            await receiver.stop()

    async def test_secret_auth_invalid(self) -> None:
        config = WebhookConfig(
            secret_header="X-Webhook-Secret",
            secret_value="my-secret-token",
        )
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, configs=(config,), port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json={"msg": "bad auth"},
                    headers={"X-Webhook-Secret": "wrong-token"},
                )
                assert resp.status == 401
            assert mgr.queue_depth == 0
        finally:
            await receiver.stop()

    async def test_no_auth_when_no_secret(self) -> None:
        config = WebhookConfig()  # no secret_header / secret_value
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, configs=(config,), port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json={"msg": "no auth needed"},
                )
                assert resp.status == 200
            assert mgr.queue_depth == 1
        finally:
            await receiver.stop()


class TestWebhookReceiverErrors:
    async def test_backpressure_429(self) -> None:
        mgr = ReceiverManager(queue_maxsize=1)
        receiver = WebhookReceiver(mgr, port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp1 = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json={"msg": "first"},
                )
                assert resp1.status == 200
                resp2 = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json={"msg": "overflow"},
                )
                assert resp2.status == 429
        finally:
            await receiver.stop()

    async def test_unsupported_content_type_415(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    data=b"some text",
                    headers={"Content-Type": "text/plain"},
                )
                assert resp.status == 415
        finally:
            await receiver.stop()


class TestWebhookExports:
    def test_import(self) -> None:
        import seerflow.receivers as mod

        assert hasattr(mod, "WebhookReceiver")
        assert hasattr(mod, "WebhookConfig")

    def test_all(self) -> None:
        import seerflow.receivers as mod

        assert "WebhookReceiver" in mod.__all__
        assert "WebhookConfig" in mod.__all__
