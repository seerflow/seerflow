"""Alert formatters for Slack, Microsoft Teams, plain JSON, CEF, and LEEF.

Each formatter is a pure function with no I/O and no side effects.

- ``format_slack``  — Slack Block Kit payload (dict)
- ``format_teams``  — Teams Adaptive Card payload (message/attachments dict)
- ``format_json``   — Flat dict with ISO 8601 timestamp
- ``format_cef``    — ArcSight Common Event Format single-line string
- ``format_leef``   — QRadar LEEF 2.0 single-line string

Unlike the dict-returning webhook formatters, ``format_cef`` and
``format_leef`` return a single ``str`` line; they are transport-decoupled and
pair with line/text sinks (syslog/webhook) rather than the JSON-POSTing webhook
dispatcher.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import seerflow
from seerflow.models.event import SeverityLevel

if TYPE_CHECKING:
    from seerflow.models.alert import Alert

# ---------------------------------------------------------------------------
# Severity colour / emoji helpers
# ---------------------------------------------------------------------------

_SEVERITY_EMOJI: dict[str, str] = {
    "TRACE": ":white_circle:",
    "INFORMATIONAL": ":large_blue_circle:",
    "NOTICE": ":large_blue_circle:",
    "WARNING": ":large_yellow_circle:",
    "ERROR": ":red_circle:",
    "CRITICAL": ":red_circle:",
    "FATAL": ":skull:",
}

_TEAMS_SEVERITY_COLOR: dict[str, str] = {
    "TRACE": "default",
    "INFORMATIONAL": "accent",
    "NOTICE": "accent",
    "WARNING": "warning",
    "ERROR": "attention",
    "CRITICAL": "attention",
    "FATAL": "attention",
}


def _severity_name(alert: Alert) -> str:
    """Return the uppercase severity label."""
    return alert.severity_id.name


def _iso_timestamp(timestamp_ns: int) -> str:
    """Convert nanosecond epoch timestamp to ISO 8601 UTC string."""
    return datetime.fromtimestamp(timestamp_ns / 1e9, tz=UTC).isoformat()


# ---------------------------------------------------------------------------
# Slack Block Kit formatter
# ---------------------------------------------------------------------------


def format_slack(alert: Alert, *, dashboard_url: str = "") -> dict:  # type: ignore[type-arg]
    """Return a Slack Block Kit payload for the given alert.

    Structure:
    - Header block   — severity emoji + rule name
    - Section block  — description + entity info
    - Fields block   — severity, entity type, risk score, dedup count
    - ATT&CK block   — tactics + techniques (omitted when both are empty)
    - Context block  — alert_id + timestamp
    - Actions block  — dashboard link button (omitted when dashboard_url is empty)
    """
    severity = _severity_name(alert)
    emoji = _SEVERITY_EMOJI.get(severity, ":large_orange_circle:")
    ts = _iso_timestamp(alert.timestamp_ns)

    blocks: list[dict] = []  # type: ignore[type-arg]

    # Header
    blocks.append(
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji}  [{severity}] {alert.rule_name}",
            },
        }
    )

    # Description + entity
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Description:* {alert.description}\n"
                    f"*Entity:* `{alert.entity_value}` ({alert.entity_type})"
                ),
            },
        }
    )

    # Key fields
    fields = [
        {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
        {"type": "mrkdwn", "text": f"*Alert Type:*\n{alert.alert_type}"},
        {"type": "mrkdwn", "text": f"*Risk Score:*\n{alert.risk_score:.2f}"},
        {"type": "mrkdwn", "text": f"*Occurrences:*\n{alert.dedup_count}"},
    ]
    blocks.append({"type": "section", "fields": fields})

    # ATT&CK section — only when at least one tactic or technique is present
    if alert.mitre_tactics or alert.mitre_techniques:
        tactics_text = ", ".join(alert.mitre_tactics) if alert.mitre_tactics else "—"
        techniques_text = ", ".join(alert.mitre_techniques) if alert.mitre_techniques else "—"
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*MITRE Tactics:*\n{tactics_text}"},
                    {"type": "mrkdwn", "text": f"*MITRE Techniques:*\n{techniques_text}"},
                ],
            }
        )

    # Context / footer
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Alert ID: `{alert.alert_id}` | {ts}",
                }
            ],
        }
    )

    if dashboard_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View in Dashboard"},
                        "url": dashboard_url,
                        "action_id": "view_dashboard",
                    }
                ],
            }
        )

    return {"blocks": blocks}


# ---------------------------------------------------------------------------
# Microsoft Teams Adaptive Card formatter
# ---------------------------------------------------------------------------


def format_teams(alert: Alert, *, dashboard_url: str = "") -> dict:  # type: ignore[type-arg]
    """Return a Teams message payload containing an Adaptive Card.

    Structure: ``{"type": "message", "attachments": [<adaptive-card>]}``

    The card uses a FactSet for structured key/value fields and a plain
    TextBlock for the description. An ``actions`` list with an ``Action.OpenUrl``
    entry is appended when ``dashboard_url`` is non-empty.
    """
    severity = _severity_name(alert)
    color = _TEAMS_SEVERITY_COLOR.get(severity, "default")
    ts = _iso_timestamp(alert.timestamp_ns)

    body: list[dict] = []  # type: ignore[type-arg]

    # Title / heading
    body.append(
        {
            "type": "TextBlock",
            "text": f"[{severity}] {alert.rule_name}",
            "weight": "bolder",
            "size": "medium",
            "color": color,
            "wrap": True,
        }
    )

    # Description
    body.append(
        {
            "type": "TextBlock",
            "text": alert.description,
            "wrap": True,
        }
    )

    # Structured facts
    facts: list[dict[str, str]] = [
        {"title": "Severity", "value": severity},
        {"title": "Alert Type", "value": alert.alert_type},
        {"title": "Entity", "value": f"{alert.entity_value} ({alert.entity_type})"},
        {"title": "Risk Score", "value": f"{alert.risk_score:.2f}"},
        {"title": "Occurrences", "value": str(alert.dedup_count)},
        {"title": "Timestamp", "value": ts},
    ]

    if alert.mitre_tactics:
        facts.append({"title": "MITRE Tactics", "value": ", ".join(alert.mitre_tactics)})
    if alert.mitre_techniques:
        facts.append({"title": "MITRE Techniques", "value": ", ".join(alert.mitre_techniques)})

    body.append({"type": "FactSet", "facts": facts})

    # Footer — alert ID
    body.append(
        {
            "type": "TextBlock",
            "text": f"Alert ID: {alert.alert_id}",
            "size": "small",
            "isSubtle": True,
            "wrap": True,
        }
    )

    card_content: dict = {  # type: ignore[type-arg]
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }

    if dashboard_url:
        card_content["actions"] = [
            {
                "type": "Action.OpenUrl",
                "title": "View in Dashboard",
                "url": dashboard_url,
            }
        ]

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card_content,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Flat JSON formatter
# ---------------------------------------------------------------------------


def format_json(alert: Alert, *, dashboard_url: str = "") -> dict:  # type: ignore[type-arg]
    """Return a flat, JSON-serializable dict representation of the alert.

    The ``timestamp`` field is ISO 8601 UTC.
    ``mitre_tactics`` and ``mitre_techniques`` are plain lists (not tuples).
    ``severity`` is the uppercase enum name string (e.g. ``"CRITICAL"``).
    ``dashboard_url`` is included only when non-empty.
    """
    result: dict = {  # type: ignore[type-arg]
        "alert_id": alert.alert_id,
        "alert_type": alert.alert_type,
        "timestamp": _iso_timestamp(alert.timestamp_ns),
        "severity": _severity_name(alert),
        "rule_name": alert.rule_name,
        "description": alert.description,
        "entity_uuid": alert.entity_uuid,
        "entity_value": alert.entity_value,
        "entity_type": alert.entity_type,
        "mitre_tactics": list(alert.mitre_tactics),
        "mitre_techniques": list(alert.mitre_techniques),
        "risk_score": alert.risk_score,
        "dedup_count": alert.dedup_count,
    }
    if dashboard_url:
        result["dashboard_url"] = dashboard_url
    return result


# ---------------------------------------------------------------------------
# CEF (ArcSight Common Event Format) formatter
# ---------------------------------------------------------------------------
#
# Grammar (CEF v0):
#   CEF:0|Vendor|Product|Version|SignatureID|Name|Severity|Extension
#
# Vendor/Product/Version are the static Seerflow product identity, NOT alert
# data, so they live in constants + the package ``__version__`` (single source
# of truth — the device version tracks releases automatically).

_CEF_VERSION = "0"
_CEF_VENDOR = "Seerflow"
_CEF_PRODUCT = "Seerflow"

# SeverityLevel (TRACE=0 .. FATAL=6) -> CEF severity (0..10). Explicit table:
# no arithmetic scaling guesswork — every level is conformance-tested.
_CEF_SEVERITY: dict[SeverityLevel, int] = {
    SeverityLevel.TRACE: 0,
    SeverityLevel.INFORMATIONAL: 2,
    SeverityLevel.NOTICE: 3,
    SeverityLevel.WARNING: 5,
    SeverityLevel.ERROR: 7,
    SeverityLevel.CRITICAL: 9,
    SeverityLevel.FATAL: 10,
}

# entity_type -> CEF dictionary key for the well-known types. Other types fall
# back to a labelled custom string (cs1/cs1Label) carrying the type name.
_CEF_ENTITY_KEY: dict[str, str] = {"ip": "src", "user": "suser", "host": "shost"}


def _cef_escape_header(value: str) -> str:
    """Escape a CEF header field: ``\\`` then ``|`` (order matters).

    CR/LF are stripped — a header newline would break the single-line record
    and CEF leaves header-newline behaviour undefined.
    """
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r", "").replace("\n", "")


def _cef_escape_extension(value: str) -> str:
    """Escape a CEF extension value: ``\\`` first, then ``=``, newline, CR."""
    return (
        value.replace("\\", "\\\\").replace("=", "\\=").replace("\n", "\\n").replace("\r", "\\r")
    )


def _cef_severity(alert: Alert) -> str:
    """Map the alert's SeverityLevel onto a CEF 0..10 integer string."""
    return str(_CEF_SEVERITY.get(alert.severity_id, 5))


def _cef_entity_pairs(alert: Alert) -> list[tuple[str, str]]:
    """Entity reference extension pairs; empty when no entity value is set."""
    if not alert.entity_value:
        return []
    key = _CEF_ENTITY_KEY.get(alert.entity_type)
    if key is not None:
        return [(key, alert.entity_value)]
    return [("cs1", alert.entity_value), ("cs1Label", alert.entity_type)]


def _cef_extension_pairs(alert: Alert) -> list[tuple[str, str]]:
    """Build ordered (key, value) extension pairs, omitting absent fields.

    Always-present core keys (rt, externalId, cnt, cn1) anchor the record; the
    remaining keys degrade gracefully — appended only when their source is set.
    """
    pairs: list[tuple[str, str]] = [
        ("rt", str(alert.timestamp_ns // 1_000_000)),
        ("externalId", alert.alert_id),
        ("cnt", str(alert.dedup_count)),
        ("cn1", f"{alert.risk_score:g}"),
        ("cn1Label", "RiskScore"),
        ("cs5", alert.alert_type),
        ("cs5Label", "AlertType"),
    ]
    pairs.extend(_cef_entity_pairs(alert))
    if alert.entity_uuid:
        pairs.extend([("cs2", alert.entity_uuid), ("cs2Label", "SeerflowEntityUUID")])
    if alert.mitre_techniques:
        techniques = ",".join(alert.mitre_techniques)
        pairs.extend([("cs3", techniques), ("cs3Label", "MitreTechniques")])
    if alert.mitre_tactics:
        tactics = ",".join(alert.mitre_tactics)
        pairs.extend([("cs4", tactics), ("cs4Label", "MitreTactics")])
    return pairs


def _cef_extension(alert: Alert) -> str:
    """Render the space-joined ``key=value`` CEF extension blob."""
    return " ".join(
        f"{key}={_cef_escape_extension(value)}" for key, value in _cef_extension_pairs(alert)
    )


def format_cef(alert: Alert) -> str:
    """Return a single-line CEF v0 string representation of the alert.

    Header: ``CEF:0|Vendor|Product|Version|SignatureID|Name|Severity|Extension``.
    ``SignatureID`` is ``rule_name`` (falling back to ``alert_type`` when empty)
    and ``Name`` is the alert description. Entity refs, MITRE technique/tactic,
    risk score, timestamp (CEF ``rt`` milliseconds) and identifiers are mapped
    into the extension; unmapped/empty fields are omitted (graceful degradation).
    """
    signature_id = alert.rule_name or alert.alert_type
    header = "|".join(
        [
            f"CEF:{_CEF_VERSION}",
            _cef_escape_header(_CEF_VENDOR),
            _cef_escape_header(_CEF_PRODUCT),
            _cef_escape_header(seerflow.__version__),
            _cef_escape_header(signature_id),
            _cef_escape_header(alert.description),
            _cef_severity(alert),
        ]
    )
    return f"{header}|{_cef_extension(alert)}"


# ---------------------------------------------------------------------------
# LEEF 2.0 (QRadar Log Event Extended Format) formatter
# ---------------------------------------------------------------------------
#
# Grammar (LEEF 2.0):
#   LEEF:2.0|Vendor|Product|Version|EventID|[DelimiterChar|]Attributes
#
# The 6th DelimiterChar field is optional; it is emitted only for a non-default
# (non-TAB) attribute delimiter so the receiver can self-discover it. Vendor/
# Product/Version are the static Seerflow product identity (NOT alert data), so
# they live in constants + the package ``__version__`` (single source of truth).

_LEEF_VERSION = "2.0"
_LEEF_VENDOR = "Seerflow"
_LEEF_PRODUCT = "Seerflow"
_LEEF_DEFAULT_DELIMITER = "\t"

# SeverityLevel (TRACE=0 .. FATAL=6) -> LEEF ``sev`` (1..10). Explicit table:
# LEEF severity is 1..10 (not 0-based like CEF), so this is its own mapping —
# every level is conformance-tested.
_LEEF_SEVERITY: dict[SeverityLevel, int] = {
    SeverityLevel.TRACE: 1,
    SeverityLevel.INFORMATIONAL: 2,
    SeverityLevel.NOTICE: 3,
    SeverityLevel.WARNING: 5,
    SeverityLevel.ERROR: 7,
    SeverityLevel.CRITICAL: 9,
    SeverityLevel.FATAL: 10,
}

# entity_type -> LEEF normalized attribute key for the well-known types. Other
# types fall back to a labelled custom string (cs1/cs1Label) carrying the type.
_LEEF_ENTITY_KEY: dict[str, str] = {
    "ip": "src",
    "user": "usrName",
    "host": "identHostName",
}


def _validate_leef_delimiter(delimiter: str) -> None:
    """Reject delimiters that would break the single-line pipe-framed grammar.

    A delimiter must be exactly one character and must be neither the header
    field separator (``|``) nor a CR/LF (which would split the record).
    """
    if len(delimiter) != 1:
        raise ValueError(f"LEEF delimiter must be a single character, got {delimiter!r}")
    if delimiter in ("|", "\r", "\n"):
        raise ValueError(f"LEEF delimiter must not be '|', CR, or LF, got {delimiter!r}")


def _leef_escape_header(value: str) -> str:
    """Escape a LEEF header field: ``\\`` then ``|`` (order matters).

    CR/LF are stripped — a header newline would break the single-line record.
    """
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r", "").replace("\n", "")


def _leef_escape_attr(value: str, delimiter: str) -> str:
    """Escape a LEEF attribute value.

    Escapes ``\\`` first, then ``=``, the active ``delimiter``, newline and CR.
    """
    escaped = (
        value.replace("\\", "\\\\").replace("=", "\\=").replace("\n", "\\n").replace("\r", "\\r")
    )
    return escaped.replace(delimiter, "\\" + delimiter)


def _leef_severity(alert: Alert) -> str:
    """Map the alert's SeverityLevel onto a LEEF 1..10 integer string."""
    return str(_LEEF_SEVERITY.get(alert.severity_id, 5))


def _leef_entity_pairs(alert: Alert) -> list[tuple[str, str]]:
    """Entity reference attribute pairs; empty when no entity value is set."""
    if not alert.entity_value:
        return []
    key = _LEEF_ENTITY_KEY.get(alert.entity_type)
    if key is not None:
        return [(key, alert.entity_value)]
    return [("cs1", alert.entity_value), ("cs1Label", alert.entity_type)]


def _leef_attr_pairs(alert: Alert) -> list[tuple[str, str]]:
    """Build ordered (key, value) attribute pairs, omitting absent fields.

    Always-present anchors (devTime, devTimeFormat, externalId, cnt, cn1) frame
    the record; remaining keys degrade gracefully — appended only when set.
    Mirrors ``_cef_extension_pairs`` field coverage with LEEF-canonical keys.
    """
    pairs: list[tuple[str, str]] = [
        ("devTime", str(alert.timestamp_ns // 1_000_000)),
        ("devTimeFormat", "epochMillis"),
        ("sev", _leef_severity(alert)),
        ("externalId", alert.alert_id),
        ("cnt", str(alert.dedup_count)),
        ("cn1", f"{alert.risk_score:g}"),
        ("cn1Label", "RiskScore"),
        ("cs5", alert.alert_type),
        ("cs5Label", "AlertType"),
    ]
    pairs.extend(_leef_entity_pairs(alert))
    if alert.entity_uuid:
        pairs.extend([("cs2", alert.entity_uuid), ("cs2Label", "SeerflowEntityUUID")])
    if alert.mitre_techniques:
        pairs.extend([("cs3", ",".join(alert.mitre_techniques)), ("cs3Label", "MitreTechniques")])
    if alert.mitre_tactics:
        pairs.extend([("cs4", ",".join(alert.mitre_tactics)), ("cs4Label", "MitreTactics")])
    return pairs


def _leef_attributes(alert: Alert, delimiter: str) -> str:
    """Render the delimiter-joined ``key=value`` LEEF attribute blob."""
    return delimiter.join(
        f"{key}={_leef_escape_attr(value, delimiter)}" for key, value in _leef_attr_pairs(alert)
    )


def format_leef(alert: Alert, *, delimiter: str = _LEEF_DEFAULT_DELIMITER) -> str:
    """Return a single-line LEEF 2.0 string representation of the alert.

    Header: ``LEEF:2.0|Vendor|Product|Version|EventID|[DelimiterChar|]Attrs``.
    ``EventID`` is ``rule_name`` (falling back to ``alert_type`` when empty).
    Entity refs, MITRE technique/tactic, risk score, timestamp (``devTime`` in
    milliseconds) and identifiers are mapped into the tab-delimited (or
    ``delimiter``-delimited) attributes; unmapped/empty fields are omitted
    (graceful degradation). The optional 6th ``DelimiterChar`` field is emitted
    only for a non-default delimiter.

    Raises ``ValueError`` if ``delimiter`` is not a single character or is one
    of ``|``, CR, or LF (each would break the pipe-framed single-line grammar).
    """
    _validate_leef_delimiter(delimiter)
    event_id = alert.rule_name or alert.alert_type
    fields = [
        f"LEEF:{_LEEF_VERSION}",
        _leef_escape_header(_LEEF_VENDOR),
        _leef_escape_header(_LEEF_PRODUCT),
        _leef_escape_header(seerflow.__version__),
        _leef_escape_header(event_id),
    ]
    if delimiter != _LEEF_DEFAULT_DELIMITER:
        fields.append(_leef_escape_header(delimiter))
    header = "|".join(fields)
    return f"{header}|{_leef_attributes(alert, delimiter)}"
