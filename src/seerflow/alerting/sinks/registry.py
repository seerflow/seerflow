"""Declarative sink type registry (S-361/FR-005).

The module top level imports nothing heavy so the config-layer validator can
read ``KNOWN_SINK_TYPES`` without pulling in transport modules (avoids a
``config -> _config_builders -> alerting`` import cycle). ``build_sink`` imports
the concrete sink lazily and returns a ``DeliveryTarget`` the
``NotificationRouter`` can register by name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.alerting.target import DeliveryTarget
    from seerflow.config import SinkConfig

# Stable type tokens accepted by ``alerting.sinks[*].type``. Adding a new
# transport (HEC/syslog/CEF/LEEF) means adding a token here + a build branch.
# ``console``/``file`` are served by the queue-backed-sink adapter; ``otlp``
# (S-366) by the OTLP batch-sink adapter.
KNOWN_SINK_TYPES: frozenset[str] = frozenset({"console", "file", "otlp"})

# Types served by the synchronous queue-backed-sink adapter. ``otlp`` is an
# async batch sink with its own ``run()`` loop, so it routes to a dedicated
# adapter instead.
_QUEUE_SINK_TYPES: frozenset[str] = frozenset({"console", "file"})


def is_known_sink_type(type_name: str) -> bool:
    """Return True iff ``type_name`` is a registered sink type."""
    return type_name in KNOWN_SINK_TYPES


def build_sink(config: SinkConfig) -> DeliveryTarget:
    """Construct a ``DeliveryTarget`` for ``config`` via its registered factory.

    Raises ``ValueError`` for an unknown type (config-layer validation should
    have rejected it first; this is the defence-in-depth fallback).
    """
    if config.type in _QUEUE_SINK_TYPES:
        from seerflow.alerting.sinks.adapter import build_queue_sink_target

        return build_queue_sink_target(config)
    if config.type == "otlp":
        from seerflow.alerting.sinks.adapter import build_otlp_sink_target

        return build_otlp_sink_target(config)
    msg = f"unknown sink type {config.type!r}; known: {sorted(KNOWN_SINK_TYPES)}"
    raise ValueError(msg)
