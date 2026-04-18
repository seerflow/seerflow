"""Email DeliveryTarget — async SMTP via aiosmtplib (S-163)."""

from __future__ import annotations

import html as _html
import logging
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import TYPE_CHECKING

import aiosmtplib

from seerflow.alerting.channels._ratelimit import TokenBucket

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.models.alert import Alert

_log = logging.getLogger("seerflow")

_SEVERITY_COLOUR: dict[int, str] = {
    0: "#888",
    1: "#888",
    2: "#888",
    3: "#c90",
    4: "#e55",
    5: "#c00",
    6: "#800",
}
_SEVERITY_NAME: dict[int, str] = {
    0: "TRACE",
    1: "INFORMATIONAL",
    2: "NOTICE",
    3: "WARNING",
    4: "ERROR",
    5: "CRITICAL",
    6: "FATAL",
}


def _sev(alert: Alert) -> str:
    return _SEVERITY_NAME.get(int(alert.severity_id), str(alert.severity_id))


def format_html(alert: Alert) -> str:
    colour = _SEVERITY_COLOUR.get(int(alert.severity_id), "#888")
    tactics = _html.escape(", ".join(alert.mitre_tactics)) or "—"
    techniques = _html.escape(", ".join(alert.mitre_techniques)) or "—"
    rule_name = _html.escape(alert.rule_name)
    description = _html.escape(alert.description)
    entity_value = _html.escape(alert.entity_value)
    entity_type = _html.escape(alert.entity_type)
    return (
        f'<div style="font-family:sans-serif">'
        f'<h2 style="color:{colour}">[{_sev(alert)}] {rule_name}</h2>'
        f"<p>{description}</p>"
        f"<ul>"
        f"<li><b>Entity:</b> {entity_value} ({entity_type})</li>"
        f"<li><b>Risk score:</b> {alert.risk_score:.2f}</li>"
        f"<li><b>ATT&amp;CK tactics:</b> {tactics}</li>"
        f"<li><b>ATT&amp;CK techniques:</b> {techniques}</li>"
        f"</ul>"
        f"</div>"
    )


def format_text(alert: Alert) -> str:
    return (
        f"[{_sev(alert)}] {alert.rule_name}\n"
        f"{alert.description}\n"
        f"Entity: {alert.entity_value} ({alert.entity_type})\n"
        f"Risk score: {alert.risk_score:.2f}\n"
    )


def format_digest_html(alerts: Sequence[Alert]) -> str:
    by_sev: dict[int, list[Alert]] = {}
    for a in alerts:
        by_sev.setdefault(int(a.severity_id), []).append(a)
    rows: list[str] = [f"<h2>Seerflow digest — {len(alerts)} alerts</h2>"]
    for sev in sorted(by_sev.keys(), reverse=True):
        rows.append(f"<h3>{_SEVERITY_NAME.get(sev, str(sev))}</h3><ul>")
        for a in by_sev[sev]:
            rule_name = _html.escape(a.rule_name)
            entity_value = _html.escape(a.entity_value)
            rows.append(f"<li>{rule_name} — {entity_value} (risk={a.risk_score:.2f})</li>")
        rows.append("</ul>")
    return "\n".join(rows)


@dataclass(frozen=True, slots=True, kw_only=True)
class EmailTarget:
    """SMTP DeliveryTarget. ``smtp_password`` is hidden from ``repr``."""

    name: str
    smtp_host: str
    smtp_port: int
    use_starttls: bool
    from_address: str
    to_addresses: tuple[str, ...]
    smtp_user: str = field(default="", repr=False)
    smtp_password: str = field(default="", repr=False)
    min_severity: int = 0
    max_per_minute: int | None = None
    _bucket: TokenBucket | None = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        bucket: TokenBucket | None = None
        if self.max_per_minute is not None:
            bucket = TokenBucket(
                rate_per_second=self.max_per_minute / 60.0,
                burst=self.max_per_minute,
            )
        object.__setattr__(self, "_bucket", bucket)

    def _build_message(self, subject: str, html: str, text: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.from_address
        msg["To"] = ", ".join(self.to_addresses)
        msg["Subject"] = subject
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        return msg

    async def _send(self, msg: EmailMessage) -> None:
        if self._bucket is not None:
            await self._bucket.acquire()
        username = self.smtp_user or None
        password = self.smtp_password if self.smtp_user else None
        try:
            await aiosmtplib.send(
                msg,
                hostname=self.smtp_host,
                port=self.smtp_port,
                start_tls=self.use_starttls,
                username=username,
                password=password,
            )
        except aiosmtplib.SMTPException:
            _log.exception("EmailTarget %s: SMTP delivery failed", self.name)
        except OSError:
            _log.exception("EmailTarget %s: transport error", self.name)

    async def deliver(self, alert: Alert) -> None:
        subject = f"[Seerflow/{_sev(alert)}] {alert.rule_name}"[:200]
        msg = self._build_message(subject, format_html(alert), format_text(alert))
        await self._send(msg)

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return
        subject = f"[Seerflow digest] {len(alerts)} alerts"
        html = format_digest_html(alerts)
        text = "\n".join(format_text(a) for a in alerts)
        await self._send(self._build_message(subject, html, text))
