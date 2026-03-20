"""Drain3 parser wrapper — streaming log template extraction."""

from __future__ import annotations

import re
from typing import Any

_IP_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)

_DEFAULT_MAX_MESSAGE_LEN = 8192


def _mask_tokens(message: str) -> str:
    """Pre-process message by masking IPs and UUIDs for better template stability."""
    masked = _IP_RE.sub("<IP>", message)
    return _UUID_RE.sub("<UUID>", masked)


def _extract_params(message: str, template: str) -> tuple[str, ...]:
    """Extract parameter values by comparing message tokens with template wildcards."""
    msg_tokens = message.split()
    tmpl_tokens = template.split()
    if len(msg_tokens) != len(tmpl_tokens):
        return ()
    return tuple(m for m, t in zip(msg_tokens, tmpl_tokens, strict=True) if t == "<*>")


class DrainParser:
    """Streaming log template extractor wrapping drain3.TemplateMiner.

    NOT thread-safe. Create one instance per thread/coroutine or protect
    with a lock. Masks IPs and UUIDs before parsing for template stability.

    Note: ``params`` in the return tuple contain values from the *masked*
    message. IPs appear as ``<IP>``, UUIDs as ``<UUID>``.
    """

    __slots__ = ("_max_message_len", "_miner")

    def __init__(
        self,
        *,
        sim_th: float = 0.4,
        depth: int = 4,
        max_clusters: int = 1000,
        max_message_len: int = _DEFAULT_MAX_MESSAGE_LEN,
    ) -> None:
        if not (0.0 < sim_th <= 1.0):
            msg = f"sim_th must be in (0.0, 1.0], got {sim_th!r}"
            raise ValueError(msg)
        if depth < 3:
            msg = f"depth must be >= 3, got {depth!r}"
            raise ValueError(msg)
        if max_clusters < 1:
            msg = f"max_clusters must be >= 1, got {max_clusters!r}"
            raise ValueError(msg)

        from drain3 import TemplateMiner
        from drain3.template_miner_config import TemplateMinerConfig

        config = TemplateMinerConfig()
        config.drain_sim_th = sim_th
        config.drain_depth = depth
        config.drain_max_clusters = max_clusters
        config.parametrize_numeric_tokens = True

        self._miner = TemplateMiner(config=config)
        self._max_message_len = max_message_len

    def parse(self, message: str) -> tuple[int, str, tuple[str, ...]]:
        """Extract template from a log message.

        Returns:
            (template_id, template_str, params) where params are the
            variable parts replaced by ``<*>`` in the template.
        """
        if not message or not message.strip():
            return -1, "", ()
        if len(message) > self._max_message_len:
            message = message[: self._max_message_len]
        message = " ".join(message.split())  # normalize whitespace
        masked = _mask_tokens(message)
        result: dict[str, Any] = self._miner.add_log_message(masked)
        template = str(result["template_mined"])
        cluster_id = int(result["cluster_id"])
        params = _extract_params(masked, template)
        return cluster_id, template, params

    @property
    def template_count(self) -> int:
        """Number of unique templates discovered so far."""
        return len(self._miner.drain.clusters)
