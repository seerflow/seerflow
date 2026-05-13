"""Tests for EmailTarget — in-process SMTP via aiosmtpd (S-163)."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import is_dataclass
from typing import TYPE_CHECKING

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import Message

from seerflow.alerting.channels.email import (
    EmailTarget,
    format_digest_html,
    format_html,
    format_text,
)
from seerflow.models.event import SeverityLevel
from tests.unit.alert_factory import make_alert

if TYPE_CHECKING:
    import email.message
    from collections.abc import Iterator


@pytest.mark.unit
def test_format_html_contains_severity_and_rule_name() -> None:
    alert = make_alert(severity_id=SeverityLevel.CRITICAL, rule_name="brute-force")
    body = format_html(alert)
    assert "CRITICAL" in body
    assert "brute-force" in body


@pytest.mark.unit
def test_format_text_has_no_html_tags() -> None:
    alert = make_alert()
    body = format_text(alert)
    assert "<" not in body
    assert ">" not in body


@pytest.mark.unit
def test_format_html_escapes_injected_script_tags() -> None:
    alert = make_alert(rule_name="<script>alert(1)</script>")
    body = format_html(alert)
    assert "<script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


@pytest.mark.unit
def test_format_digest_html_escapes_injected_rule_name() -> None:
    alerts = [make_alert(rule_name='<img src=x onerror="alert(1)">')]
    body = format_digest_html(alerts)
    assert "<img" not in body
    assert "&lt;img" in body


@pytest.mark.unit
def test_format_digest_html_orders_by_severity_descending() -> None:
    alerts = [
        make_alert(severity_id=SeverityLevel.WARNING, rule_name="warn-rule"),
        make_alert(severity_id=SeverityLevel.CRITICAL, rule_name="crit-rule"),
    ]
    body = format_digest_html(alerts)
    assert body.index("CRITICAL") < body.index("WARNING")
    assert "crit-rule" in body
    assert "warn-rule" in body


@pytest.mark.unit
def test_email_target_is_frozen_and_hides_password() -> None:
    t = EmailTarget(
        name="oncall-email",
        smtp_host="smtp.example.com",
        smtp_port=587,
        use_starttls=True,
        smtp_user="user",
        smtp_password="supersecret",
        from_address="alerts@x.io",
        to_addresses=("oncall@x.io",),
    )
    assert is_dataclass(t)
    assert "supersecret" not in repr(t)


class _CapturingHandler(Message):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[email.message.Message] = []

    def handle_message(self, message: email.message.Message) -> None:
        self.messages.append(message)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def smtp_controller() -> Iterator[tuple[Controller, _CapturingHandler]]:
    handler = _CapturingHandler()
    controller = Controller(handler, hostname="127.0.0.1", port=_free_port())
    controller.start()
    try:
        yield controller, handler
    finally:
        controller.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_email_deliver_strips_crlf_from_subject(
    smtp_controller: tuple[Controller, _CapturingHandler],
) -> None:
    controller, handler = smtp_controller
    target = EmailTarget(
        name="t",
        smtp_host="127.0.0.1",
        smtp_port=controller.port,
        use_starttls=False,
        from_address="a@x.io",
        to_addresses=("b@x.io",),
    )
    import asyncio as _asyncio

    await target.deliver(make_alert(rule_name="rule\r\nBcc: leak@evil"))
    for _ in range(20):
        if handler.messages:
            break
        await _asyncio.sleep(0.05)
    assert len(handler.messages) == 1
    msg = handler.messages[0]
    subject = msg["Subject"]
    assert "\r" not in subject
    assert "\n" not in subject
    # No injected header — "Bcc:" only appears inside the Subject body, not as
    # a separate header recognised by the SMTP relay.
    assert msg["Bcc"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_email_deliver_sends_html_multipart(
    smtp_controller: tuple[Controller, _CapturingHandler],
) -> None:
    controller, handler = smtp_controller
    target = EmailTarget(
        name="t",
        smtp_host="127.0.0.1",
        smtp_port=controller.port,
        use_starttls=False,
        smtp_user="",
        smtp_password="",
        from_address="alerts@x.io",
        to_addresses=("oncall@x.io",),
    )
    await target.deliver(make_alert(severity_id=SeverityLevel.ERROR))
    for _ in range(20):
        if handler.messages:
            break
        await asyncio.sleep(0.05)
    assert len(handler.messages) == 1
    msg = handler.messages[0]
    assert msg["From"] == "alerts@x.io"
    assert msg["To"] == "oncall@x.io"
    assert msg.is_multipart()
    types = {p.get_content_type() for p in msg.walk()}
    assert "text/html" in types
    assert "text/plain" in types


@pytest.mark.integration
@pytest.mark.asyncio
async def test_email_digest_sends_single_email_with_count_in_subject(
    smtp_controller: tuple[Controller, _CapturingHandler],
) -> None:
    controller, handler = smtp_controller
    target = EmailTarget(
        name="t",
        smtp_host="127.0.0.1",
        smtp_port=controller.port,
        use_starttls=False,
        smtp_user="",
        smtp_password="",
        from_address="alerts@x.io",
        to_addresses=("oncall@x.io",),
    )
    alerts = [make_alert() for _ in range(5)]
    await target.deliver_digest(alerts)
    for _ in range(20):
        if handler.messages:
            break
        await asyncio.sleep(0.05)
    assert len(handler.messages) == 1
    assert "5 alerts" in handler.messages[0]["Subject"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_email_digest_with_empty_list_does_not_send() -> None:
    target = EmailTarget(
        name="t",
        smtp_host="127.0.0.1",
        smtp_port=1,
        use_starttls=False,
        from_address="alerts@x.io",
        to_addresses=("oncall@x.io",),
    )
    await target.deliver_digest([])
