"""Tests for WebhookReceiver — generic HTTP POST ingestion with field mapping."""

from __future__ import annotations

import json

import aiohttp
import pytest

from seerflow.receivers.base import Receiver
from seerflow.receivers.manager import ReceiverManager
from seerflow.receivers.webhook import WebhookConfig, WebhookReceiver


class TestWebhookReceiverProtocol:
    def test_isinstance_receiver(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        assert isinstance(receiver, Receiver)


class TestWebhookConfig:
    def test_half_configured_auth_raises(self) -> None:
        with pytest.raises(ValueError, match="auth_header and auth_token"):
            WebhookConfig(auth_header="X-Token")

    def test_half_configured_token_raises(self) -> None:
        with pytest.raises(ValueError, match="auth_header and auth_token"):
            WebhookConfig(auth_token="secret")

    def test_both_set_ok(self) -> None:
        cfg = WebhookConfig(auth_header="X-Token", auth_token="secret")
        assert cfg.auth_header == "X-Token"

    def test_both_empty_ok(self) -> None:
        cfg = WebhookConfig()
        assert cfg.auth_header == ""


class TestWebhookReceiverLifecycle:
    async def test_start_stop_lifecycle(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        assert not receiver.is_healthy()
        await receiver.start()
        assert receiver.is_healthy()
        await receiver.stop()
        assert not receiver.is_healthy()

    async def test_double_start_idempotent(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        await receiver.start()
        port1 = receiver.actual_port
        await receiver.start()
        assert receiver.actual_port == port1
        await receiver.stop()

    async def test_double_stop_idempotent(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        await receiver.start()
        await receiver.stop()
        await receiver.stop()
        assert not receiver.is_healthy()

    def test_empty_bind_addr_raises(self) -> None:
        mgr = ReceiverManager()
        with pytest.raises(ValueError, match="bind_addr"):
            WebhookReceiver(mgr, bind_addr="", port=0)


class TestWebhookReceiverIngest:
    async def test_receive_json(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json={"message": "hello world", "level": "info"},
                )
                assert resp.status == 200
            event = await mgr.get_event()
            assert event.source_type == "webhook"
            parsed = json.loads(event.data)
            assert parsed["message"] == "hello world"
        finally:
            await receiver.stop()

    async def test_receive_form_encoded(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    data={"message": "form hello"},
                )
                assert resp.status == 200
            event = await mgr.get_event()
            parsed = json.loads(event.data)
            assert parsed["message"] == "form hello"
        finally:
            await receiver.stop()

    async def test_field_mapping(self) -> None:
        config = WebhookConfig(
            field_mapping={"severity": "level", "msg": "message"},
            source_id="mapped",
        )
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, configs=(config,), port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json={"message": "mapped msg", "level": "error"},
                )
                assert resp.status == 200
            event = await mgr.get_event()
            assert event.metadata["severity"] == "error"
            assert event.metadata["msg"] == "mapped msg"
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
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json={"body": {"text": "nested"}, "meta": {"host": "srv-01"}},
                )
                assert resp.status == 200
            event = await mgr.get_event()
            assert event.metadata["body_text"] == "nested"
            assert event.metadata["host"] == "srv-01"
        finally:
            await receiver.stop()

    async def test_missing_field_mapping_skipped(self) -> None:
        config = WebhookConfig(
            field_mapping={"found": "exists", "missing": "no.such.path"},
        )
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, configs=(config,), port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json={"exists": "here"},
                )
                assert resp.status == 200
            event = await mgr.get_event()
            assert event.metadata["found"] == "here"
            assert "missing" not in event.metadata
        finally:
            await receiver.stop()


class TestWebhookReceiverAuth:
    async def test_auth_valid(self) -> None:
        config = WebhookConfig(
            auth_header="X-Webhook-Secret",
            auth_token="my-secret-token",
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
        finally:
            await receiver.stop()

    async def test_auth_invalid(self) -> None:
        config = WebhookConfig(
            auth_header="X-Webhook-Secret",
            auth_token="my-secret-token",
        )
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, configs=(config,), port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json={"msg": "bad"},
                    headers={"X-Webhook-Secret": "wrong"},
                )
                assert resp.status == 401
        finally:
            await receiver.stop()

    async def test_no_auth_when_no_config(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    json={"msg": "no auth"},
                )
                assert resp.status == 200
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
                    data=b"text",
                    headers={"Content-Type": "text/plain"},
                )
                assert resp.status == 415
        finally:
            await receiver.stop()

    async def test_malformed_json_400(self) -> None:
        mgr = ReceiverManager()
        receiver = WebhookReceiver(mgr, port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/ingest/webhook",
                    data=b"{not valid json",
                    headers={"Content-Type": "application/json"},
                )
                assert resp.status == 400
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
