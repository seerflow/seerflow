"""S-226 — verify the new _threat_intel_builders module exposes the expected surface."""

from __future__ import annotations

import importlib


def test_module_imports() -> None:
    mod = importlib.import_module("seerflow._threat_intel_builders")
    for name in (
        "_build_taxii_auth_config",
        "_build_taxii_feed_config",
        "_require_taxii_str",
        "_require_taxii_int",
        "_require_taxii_optional_int",
        "_require_taxii_bool",
        "_require_taxii_auth",
        "_build_threat_intel_config",
        "build_seerflow_config",
    ):
        assert hasattr(mod, name), f"missing {name}"


def test_build_seerflow_config_default() -> None:
    from seerflow._threat_intel_builders import build_seerflow_config

    cfg = build_seerflow_config({})
    assert cfg.threat_intel.enabled is False
    assert cfg.threat_intel.feeds == ()
