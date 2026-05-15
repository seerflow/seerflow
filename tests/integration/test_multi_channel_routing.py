"""End-to-end: one alert routed to all four channel kinds via the router (S-163)."""

from __future__ import annotations

import asyncio
import socket
from typing import TYPE_CHECKING

import aiohttp
import pytest
from aioresponses import aioresponses
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import Message

if TYPE_CHECKING:
    import email.message
    from collections.abc import Iterator

from seerflow.alerting.channels import bind_http_channel
from seerflow.alerting.channels.email import EmailTarget
from seerflow.alerting.channels.sms import SmsTarget
from seerflow.alerting.channels.telegram import TelegramTarget
from seerflow.alerting.channels.whatsapp import WhatsAppTarget
from seerflow.alerting.router import (
    DefaultRouting,
    NotificationRouter,
    RoutingRule,
    RoutingRuleMatch,
    RoutingRuleNotify,
)
from seerflow.models.event import SeverityLevel
from tests.unit.alert_factory import make_alert


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _CapturingHandler(Message):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[email.message.Message] = []

    def handle_message(self, message: email.message.Message) -> None:
        self.messages.append(message)


@pytest.fixture
def smtp_controller() -> Iterator[tuple[Controller, _CapturingHandler]]:
    handler = _CapturingHandler()
    port = _free_port()
    controller = Controller(handler, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield controller, handler
    finally:
        controller.stop()


@pytest.mark.integration
async def test_router_fans_out_to_all_four_channels(
    smtp_controller: tuple[Controller, _CapturingHandler],
) -> None:
    controller, handler = smtp_controller

    email_t = EmailTarget(
        name="em",
        smtp_host="127.0.0.1",
        smtp_port=controller.port,
        use_starttls=False,
        from_address="a@x",
        to_addresses=("b@x",),
    )
    sms_t = SmsTarget(
        name="sm",
        account_sid="AC",
        auth_token="t",
        from_number="+1",
        to_numbers=("+2",),
        rate_per_second=100.0,
        burst=10,
    )
    tg_t = TelegramTarget(
        name="tg",
        bot_token="t:ABC",
        chat_id="-1",
        rate_per_second=100.0,
        burst=10,
    )
    wa_t = WhatsAppTarget(
        name="wa",
        phone_number_id="PID",
        access_token="tok",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+3",),
        rate_per_second=100.0,
        burst=10,
    )

    with aioresponses() as mock:
        mock.post(
            "https://api.twilio.com/2010-04-01/Accounts/AC/Messages.json",
            status=201,
        )
        mock.post(
            "https://api.telegram.org/bott:ABC/sendMessage",
            status=200,
            payload={"ok": True},
        )
        mock.post(
            "https://graph.facebook.com/v18.0/PID/messages",
            status=200,
            payload={"messages": []},
        )
        async with aiohttp.ClientSession() as session:
            targets = (
                email_t,
                bind_http_channel(sms_t, session=session),  # type: ignore[arg-type]
                bind_http_channel(tg_t, session=session),  # type: ignore[arg-type]
                bind_http_channel(wa_t, session=session),  # type: ignore[arg-type]
            )
            router = NotificationRouter(
                targets=targets,
                rules=(
                    RoutingRule(
                        match=RoutingRuleMatch(),
                        notify=(
                            RoutingRuleNotify(channel="em", mode="immediate"),
                            RoutingRuleNotify(channel="sm", mode="immediate"),
                            RoutingRuleNotify(channel="tg", mode="immediate"),
                            RoutingRuleNotify(channel="wa", mode="immediate"),
                        ),
                    ),
                ),
                default_routing=DefaultRouting(action="drop"),
            )
            await router.route(make_alert(severity_id=SeverityLevel.CRITICAL))
            for _ in range(30):
                if handler.messages:
                    break
                await asyncio.sleep(0.05)
            await router.stop()

    assert len(handler.messages) == 1, "email target did not receive the alert"
    # aioresponses records every POST in .requests keyed by (method, URL).
    twilio_key = ("POST", "https://api.twilio.com/2010-04-01/Accounts/AC/Messages.json")
    telegram_key = ("POST", "https://api.telegram.org/bott:ABC/sendMessage")
    whatsapp_key = ("POST", "https://graph.facebook.com/v18.0/PID/messages")
    assert any(twilio_key == (m, str(u)) for (m, u), _ in mock.requests.items()), (
        "SMS target was not invoked"
    )
    assert any(telegram_key == (m, str(u)) for (m, u), _ in mock.requests.items()), (
        "Telegram target was not invoked"
    )
    assert any(whatsapp_key == (m, str(u)) for (m, u), _ in mock.requests.items()), (
        "WhatsApp target was not invoked"
    )
