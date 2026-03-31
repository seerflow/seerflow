"""YAML correlation rule parser and loader.

Validates raw YAML dicts against the schema and converts them to
``CorrelationRule`` objects.  All regex patterns are compiled to
catch syntax errors at load time rather than at match time.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from seerflow.models.alert import CorrelationRule, SourceCondition
from seerflow.models.event import SeverityLevel

_log = logging.getLogger("seerflow")

_VALID_ENTITY_TYPES = frozenset({"user", "ip", "host", "process", "file", "domain"})
_MAX_PATTERN_LENGTH = 512
_VALID_CONDITION_FIELDS = frozenset(
    {
        "message",
        "source_type",
        "source_id",
        "template_str",
        "severity_id",
        "entity_refs",
        "related_ips",
        "related_users",
        "related_hosts",
    }
)


class RuleValidationError(Exception):
    """Raised when a correlation rule YAML dict is invalid."""


def _validate_sources(
    sources_raw: list[dict[str, Any]],
) -> tuple[SourceCondition, ...]:
    """Parse and validate the ``sources`` list from a rule dict."""
    if not isinstance(sources_raw, list) or len(sources_raw) == 0:
        msg = "Rule must have at least one source"
        raise RuleValidationError(msg)

    sources: list[SourceCondition] = []
    for i, src in enumerate(sources_raw):
        source_type = src.get("source_type")
        if not source_type or not isinstance(source_type, str):
            msg = f"sources[{i}].source_type must be a non-empty string"
            raise RuleValidationError(msg)

        conditions = src.get("conditions", {})
        if not isinstance(conditions, dict):
            msg = f"sources[{i}].conditions must be a dict"
            raise RuleValidationError(msg)

        for field, pattern in conditions.items():
            if field not in _VALID_CONDITION_FIELDS:
                msg = f"sources[{i}].conditions key '{field}' is not in the allowed field list"
                raise RuleValidationError(msg)
            if not isinstance(pattern, str):
                msg = f"sources[{i}].conditions['{field}'] must be a string"
                raise RuleValidationError(msg)
            if len(pattern) > _MAX_PATTERN_LENGTH:
                msg = (
                    f"sources[{i}].conditions['{field}'] regex exceeds {_MAX_PATTERN_LENGTH} chars"
                )
                raise RuleValidationError(msg)
            try:
                re.compile(pattern)
            except re.error as exc:
                msg = f"sources[{i}].conditions['{field}'] has invalid regex: {exc}"
                raise RuleValidationError(msg) from exc

        min_count = src.get("min_count", 1)
        if not isinstance(min_count, int) or isinstance(min_count, bool) or min_count < 1:
            msg = f"sources[{i}].min_count must be a positive integer, got {min_count!r}"
            raise RuleValidationError(msg)
        sources.append(
            SourceCondition(
                source_type=source_type,
                conditions={str(k): str(v) for k, v in conditions.items()},
                min_count=min_count,
            )
        )

    return tuple(sources)


def parse_rule_yaml(data: dict[str, Any]) -> CorrelationRule:
    """Parse and validate a raw YAML dict into a ``CorrelationRule``.

    Raises ``RuleValidationError`` on schema violations, invalid regex
    patterns, or out-of-range values.
    """
    # --- required: name ---
    name = data.get("name")
    if not name or not isinstance(name, str):
        msg = "Rule must have a 'name' string field"
        raise RuleValidationError(msg)

    # --- required: entity_type ---
    entity_type = data.get("entity_type")
    if entity_type not in _VALID_ENTITY_TYPES:
        msg = f"entity_type must be one of {sorted(_VALID_ENTITY_TYPES)}, got {entity_type!r}"
        raise RuleValidationError(msg)

    # --- required: window_seconds ---
    window_seconds = data.get("window_seconds")
    if (
        not isinstance(window_seconds, int)
        or isinstance(window_seconds, bool)
        or window_seconds <= 0
    ):
        msg = f"window_seconds must be a positive integer, got {window_seconds!r}"
        raise RuleValidationError(msg)

    # --- optional: min_sources (default 1) ---
    min_sources = data.get("min_sources", 1)
    if not isinstance(min_sources, int) or isinstance(min_sources, bool) or min_sources < 1:
        msg = f"min_sources must be >= 1, got {min_sources!r}"
        raise RuleValidationError(msg)

    # --- required: alert_severity ---
    alert_severity = data.get("alert_severity")
    if (
        not isinstance(alert_severity, int)
        or isinstance(alert_severity, bool)
        or not (0 <= alert_severity <= 6)
    ):
        msg = f"alert_severity must be 0-6, got {alert_severity!r}"
        raise RuleValidationError(msg)

    # --- required: sources ---
    sources = _validate_sources(data.get("sources", []))

    # --- cross-field: min_sources vs len(sources) ---
    if min_sources > len(sources):
        msg = f"min_sources ({min_sources}) cannot exceed number of sources ({len(sources)})"
        raise RuleValidationError(msg)

    # --- optional fields ---
    description = str(data.get("description", ""))
    mitre_tactics = tuple(data.get("mitre_tactics", ()))
    mitre_techniques = tuple(data.get("mitre_techniques", ()))

    return CorrelationRule(
        name=name,
        entity_type=entity_type,
        window_seconds=window_seconds,
        sources=sources,
        min_sources=min_sources,
        alert_severity=SeverityLevel(alert_severity),
        mitre_tactics=mitre_tactics,
        mitre_techniques=mitre_techniques,
        description=description,
    )


def load_correlation_rules(
    dirs: list[str] | tuple[str, ...],
) -> list[CorrelationRule]:
    """Load and validate correlation rules from YAML files in directories.

    Skips invalid rules with a warning log. Returns valid rules only.
    """
    rules: list[CorrelationRule] = []
    for dir_path in dirs:
        path = Path(dir_path)
        if not path.is_dir():
            _log.warning("Correlation rule directory does not exist: %s", dir_path)
            continue
        for yml_file in sorted({*path.glob("*.yml"), *path.glob("*.yaml")}):
            try:
                with yml_file.open() as f:
                    data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    _log.warning("Skipping %s: not a valid YAML mapping", yml_file)
                    continue
                rule = parse_rule_yaml(data)
                rules.append(rule)
            except (RuleValidationError, yaml.YAMLError) as exc:
                _log.warning(
                    "Skipping invalid correlation rule %s: %s",
                    yml_file.name,
                    exc,
                )
    return rules
