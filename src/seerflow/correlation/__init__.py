"""Cross-source correlation: entity graph, temporal windows, rules."""

from seerflow.correlation.engine import CorrelationEngine
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
    "EntityWindowBuffer",
    "RiskEntry",
    "RiskRegister",
    "RuleValidationError",
    "Watermark",
    "load_correlation_rules",
    "parse_rule_yaml",
]
