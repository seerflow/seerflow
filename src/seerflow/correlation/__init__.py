"""Cross-source correlation: entity graph, temporal windows, rules."""

from seerflow.correlation.bundled import get_bundled_rule_dir
from seerflow.correlation.engine import CorrelationEngine
from seerflow.correlation.holders import EngineHolder
from seerflow.correlation.risk import RiskEntry, RiskRegister
from seerflow.correlation.rule_loader import (
    RuleValidationError,
    load_correlation_rules,
    parse_rule_yaml,
)
from seerflow.correlation.watermark import Watermark
from seerflow.correlation.window import EntityWindowBuffer

__all__ = [
    "CorrelationEngine",
    "EngineHolder",
    "EntityWindowBuffer",
    "RiskEntry",
    "RiskRegister",
    "RuleValidationError",
    "Watermark",
    "get_bundled_rule_dir",
    "load_correlation_rules",
    "parse_rule_yaml",
]
