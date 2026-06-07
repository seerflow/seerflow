"""Unit tests for PluginsConfig and its builder (S-369)."""

from __future__ import annotations

import pytest

from seerflow._config_builders import _build_plugins
from seerflow.config import ConfigError, PluginsConfig, SeerflowConfig
from seerflow.plugins.groups import KNOWN_PLUGIN_GROUPS


@pytest.mark.unit
def test_plugins_config_disabled_by_default() -> None:
    cfg = SeerflowConfig()
    assert cfg.plugins.enabled is False
    assert frozenset(cfg.plugins.groups) == KNOWN_PLUGIN_GROUPS


@pytest.mark.unit
def test_plugins_config_is_frozen() -> None:
    import dataclasses

    cfg = PluginsConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.enabled = True  # type: ignore[misc]


@pytest.mark.unit
def test_build_plugins_defaults_to_disabled_all_groups() -> None:
    cfg = _build_plugins({})
    assert cfg.enabled is False
    assert frozenset(cfg.groups) == KNOWN_PLUGIN_GROUPS


@pytest.mark.unit
def test_build_plugins_honours_enabled_flag() -> None:
    cfg = _build_plugins({"enabled": True})
    assert cfg.enabled is True


@pytest.mark.unit
def test_build_plugins_rejects_non_bool_enabled() -> None:
    with pytest.raises(ConfigError, match=r"plugins\.enabled must be a boolean"):
        _build_plugins({"enabled": "yes"})


@pytest.mark.unit
def test_build_plugins_restricts_groups_allow_list() -> None:
    cfg = _build_plugins({"enabled": True, "groups": ["seerflow.receivers"]})
    assert cfg.groups == ("seerflow.receivers",)


@pytest.mark.unit
def test_build_plugins_rejects_unknown_group() -> None:
    with pytest.raises(ConfigError, match="unknown plugin group"):
        _build_plugins({"groups": ["seerflow.bogus"]})


@pytest.mark.unit
def test_build_plugins_rejects_non_list_groups() -> None:
    with pytest.raises(ConfigError, match=r"plugins\.groups must be a list"):
        _build_plugins({"groups": "seerflow.receivers"})
