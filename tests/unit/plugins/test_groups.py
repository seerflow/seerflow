"""Unit tests for plugin group constants and Protocol mapping (S-369)."""

from __future__ import annotations

import pytest

from seerflow.alerting.target import DeliveryTarget
from seerflow.plugins.groups import (
    KNOWN_PLUGIN_GROUPS,
    PluginGroup,
    protocol_for_group,
)
from seerflow.receivers.base import Receiver
from seerflow.storage.protocols import StorageBackend


@pytest.mark.unit
def test_known_group_strings_are_documented_values() -> None:
    assert (
        frozenset(
            {
                "seerflow.receivers",
                "seerflow.delivery_targets",
                "seerflow.storage_backends",
            }
        )
        == KNOWN_PLUGIN_GROUPS
    )


@pytest.mark.unit
def test_plugin_group_enum_values_match_group_strings() -> None:
    assert PluginGroup.RECEIVERS.value == "seerflow.receivers"
    assert PluginGroup.DELIVERY_TARGETS.value == "seerflow.delivery_targets"
    assert PluginGroup.STORAGE_BACKENDS.value == "seerflow.storage_backends"
    assert {g.value for g in PluginGroup} == KNOWN_PLUGIN_GROUPS


@pytest.mark.unit
def test_protocol_for_group_returns_the_runtime_checkable_protocol() -> None:
    assert protocol_for_group("seerflow.receivers") is Receiver
    assert protocol_for_group("seerflow.delivery_targets") is DeliveryTarget
    assert protocol_for_group("seerflow.storage_backends") is StorageBackend


@pytest.mark.unit
def test_protocol_for_group_accepts_plugin_group_enum() -> None:
    assert protocol_for_group(PluginGroup.RECEIVERS) is Receiver


@pytest.mark.unit
def test_protocol_for_group_unknown_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown plugin group"):
        protocol_for_group("seerflow.not_a_group")
