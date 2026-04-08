"""Alert formatters for Slack, Microsoft Teams, and plain JSON.

Each formatter is a pure function: takes an Alert, returns a JSON-serializable
dict. No I/O, no side effects.

- ``format_slack``  — Slack Block Kit payload
- ``format_teams``  — Teams Adaptive Card payload (message/attachments envelope)
- ``format_json``   — Flat dict with ISO 8601 timestamp
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

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
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "View in Dashboard"},
                "url": dashboard_url,
                "action_id": "view_dashboard",
            }],
        })

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
        card_content["actions"] = [{
            "type": "Action.OpenUrl",
            "title": "View in Dashboard",
            "url": dashboard_url,
        }]

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
