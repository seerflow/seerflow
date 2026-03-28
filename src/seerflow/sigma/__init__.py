"""Sigma rule engine for deterministic detection of known attack patterns."""

from seerflow.sigma.bundled import get_bundled_rule_paths
from seerflow.sigma.engine import SigmaEngine
from seerflow.sigma.loader import discover_custom_rules

__all__ = ["SigmaEngine", "discover_custom_rules", "get_bundled_rule_paths"]
