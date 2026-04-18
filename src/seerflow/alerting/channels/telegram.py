"""Telegram Bot API DeliveryTarget (S-163)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from seerflow.alerting._http import post_with_retry
from seerflow.alerting.channels._ratelimit import TokenBucket

if TYPE_CHECKING:
    from collections.abc import Sequence

    import aiohttp

    from seerflow.models.alert import Alert

_TELEGRAM_HOST = "api.telegram.org"
_TG_MAX = 4096

_MD_V2_RESERVED = frozenset("_*[]()~`>#+-=|{}.!")

_SEVERITY_NAME: dict[int, str] = {
    5: "CRITICAL",
    6: "FATAL",
    4: "ERROR",
    3: "WARNING",
    2: "NOTICE",
    1: "INFO",
    0: "TRACE",
}


def escape_markdown_v2(text: str) -> str:
    return "".join(("\\" + c) if c in _MD_V2_RESERVED else c for c in text)


def _sev_name(sev: int) -> str:
    return _SEVERITY_NAME.get(sev, str(sev))


def _truncate(raw: str) -> str:
    if len(raw) <= _TG_MAX:
        return raw
    return raw[: _TG_MAX - 1] + "…"


def format_telegram_body(alert: Alert) -> str:
    sev = escape_markdown_v2(f"[{_sev_name(int(alert.severity_id))}]")
    rule = escape_markdown_v2(alert.rule_name)
    desc = escape_markdown_v2(alert.description)
    entity = escape_markdown_v2(alert.entity_value)
    raw = f"*{sev}* {rule}\n{desc}\nEntity: `{entity}`"
    return _truncate(raw)


def format_telegram_digest(alerts: Sequence[Alert]) -> str:
    ranked = sorted(alerts, key=lambda a: int(a.severity_id), reverse=True)
    top = ranked[:10]
    remainder = len(ranked) - len(top)
    lines = [f"*Seerflow digest* — {len(ranked)} alerts"]
    for a in top:
        sev = escape_markdown_v2(f"[{_sev_name(int(a.severity_id))}]")
        rule = escape_markdown_v2(a.rule_name)
        lines.append(f"• {sev} {rule}")
    if remainder > 0:
        # `+` is reserved in MarkdownV2 so it is escaped here too.
        lines.append(f"\\+{remainder} more")
    return _truncate("\n".join(lines))


@dataclass(frozen=True, slots=True, kw_only=True)
class TelegramTarget:
    """Telegram Bot API DeliveryTarget. ``bot_token`` hidden from ``repr``."""

    name: str
    chat_id: str
    bot_token: str = field(default="", repr=False)
    min_severity: int = 0
    rate_per_second: float = 30.0
    burst: int = 30
    _bucket: TokenBucket = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_bucket", TokenBucket(self.rate_per_second, self.burst))

    def _url(self) -> str:
        return f"https://{_TELEGRAM_HOST}/bot{self.bot_token}/sendMessage"

    async def _post(self, session: aiohttp.ClientSession, text: str) -> None:
        await self._bucket.acquire()
        await post_with_retry(
            session,
            self._url(),
            {"chat_id": self.chat_id, "text": text, "parse_mode": "MarkdownV2"},
            masked_for_log=f"telegram/{self.chat_id}",
        )

    async def deliver(self, alert: Alert, *, session: aiohttp.ClientSession) -> None:
        await self._post(session, format_telegram_body(alert))

    async def deliver_digest(
        self, alerts: Sequence[Alert], *, session: aiohttp.ClientSession
    ) -> None:
        if not alerts:
            return
        await self._post(session, format_telegram_digest(alerts))
