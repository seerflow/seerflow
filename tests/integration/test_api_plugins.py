"""Integration tests for GET /api/v1/plugins inventory endpoint (S-370 AC-4)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.plugins.groups import PluginGroup
from seerflow.plugins.lifecycle import PluginInventory, PluginStatus
from seerflow.plugins.records import LoadedPlugins, PluginRecord

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi import FastAPI

    from seerflow.models.alert import Alert


class _Receiver:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def is_healthy(self) -> bool:
        return True


class _Target:
    @property
    def name(self) -> str:
        return "t1"

    @property
    def min_severity(self) -> int:
        return 0

    async def deliver(self, alert: Alert) -> None: ...
    async def deliver_digest(self, alerts: Sequence[Alert]) -> None: ...


def _alert_store() -> MagicMock:
    store = MagicMock()
    store.get_feedback_stats = AsyncMock(return_value={"tp": 0, "fp": 0})
    return store


def _app_with_inventory(inventory: PluginInventory | None) -> FastAPI:
    app = create_api_app(log_store=MagicMock(), alert_store=_alert_store())
    if inventory is not None:
        app.state.plugins = inventory
    return app


@pytest.mark.integration
def test_plugins_endpoint_returns_inventory() -> None:
    loaded = LoadedPlugins(
        records=(
            PluginRecord(
                group=PluginGroup.RECEIVERS,
                name="acme-receiver",
                distribution="acme-plugins",
                version="1.2.3",
                instance=_Receiver(),
            ),
            PluginRecord(
                group=PluginGroup.DELIVERY_TARGETS,
                name="acme-target",
                distribution="acme-plugins",
                version="4.5.6",
                instance=_Target(),
            ),
        )
    )
    inventory = PluginInventory(loaded)
    inventory._set_status("seerflow.receivers:acme-receiver", PluginStatus.STARTED)

    with TestClient(_app_with_inventory(inventory)) as client:
        resp = client.get("/api/v1/plugins")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    rows = {row["id"]: row for row in body["plugins"]}

    receiver = rows["seerflow.receivers:acme-receiver"]
    assert receiver["version"] == "1.2.3"
    assert receiver["protocol"] == "Receiver"
    assert receiver["status"] == "started"

    target = rows["seerflow.delivery_targets:acme-target"]
    assert target["version"] == "4.5.6"
    assert target["protocol"] == "DeliveryTarget"
    assert target["status"] == "loaded"


@pytest.mark.integration
def test_plugins_endpoint_empty_when_no_inventory() -> None:
    with TestClient(_app_with_inventory(None)) as client:
        resp = client.get("/api/v1/plugins")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["plugins"] == []


@pytest.mark.integration
def test_plugins_endpoint_empty_inventory_object() -> None:
    inventory = PluginInventory(LoadedPlugins())
    with TestClient(_app_with_inventory(inventory)) as client:
        resp = client.get("/api/v1/plugins")

    assert resp.status_code == 200
    assert resp.json() == {"plugins": [], "total": 0}
