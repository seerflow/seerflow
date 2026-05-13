"""``seerflow status`` — query a running Seerflow daemon's health and stats (S-075).

Issues two GETs against the running FastAPI app (``/api/v1/health`` +
``/api/v1/stats``), prints a human-readable two-column table to stdout
(or JSON when ``--json`` is set), and exits ``0`` healthy, ``2`` degraded,
``3`` unreachable.

Host + port come from the same config file the daemon was started with —
``config.health_bind_address`` and ``config.dashboard_port``. The CLI does
not accept arbitrary URLs; an operator cannot mis-target the request.
"""

# ruff: noqa: T201 — print() is the correct output mechanism for CLI commands.

from __future__ import annotations

import argparse  # noqa: TC003 — used at runtime by run_status type hints
import json
import sys
from typing import Any

import httpx

from seerflow.config import load_config

EXIT_HEALTHY = 0
EXIT_DEGRADED = 2
EXIT_UNREACHABLE = 3

_REQUEST_TIMEOUT_DEFAULT_S = 3.0


def _load_endpoint(args: argparse.Namespace) -> tuple[str, int]:
    """Return ``(host, port)`` from the operator's config file.

    The CLI deliberately does not accept an arbitrary URL — the same
    config the daemon started with tells the client where to connect.
    """
    config = load_config(getattr(args, "config", None))
    return config.health_bind_address, config.dashboard_port


async def _fetch(host: str, port: int, timeout: float) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch ``/api/v1/health`` and ``/api/v1/stats`` from the running daemon.

    Returns ``(health_body, stats_body)``. Raises on transport errors
    (``httpx.ConnectError``, ``httpx.TimeoutException``) and on bodies that
    are not parseable as JSON — ``run_status`` maps these to exit code 3.

    Health responses with a 503 status are still returned (the body is
    well-formed and carries ``status: degraded``); ``run_status`` inspects
    the ``status`` field rather than the HTTP code.
    """
    base = f"http://{host}:{port}/api/v1"
    async with httpx.AsyncClient(timeout=timeout) as client:
        # Health: 503 is the daemon saying "degraded" — accept the body.
        health_resp = await client.get(f"{base}/health")
        health_body = health_resp.json()
        stats_resp = await client.get(f"{base}/stats")
        stats_resp.raise_for_status()
        stats_body = stats_resp.json()
    if not isinstance(health_body, dict) or not isinstance(stats_body, dict):
        msg = "unexpected non-object body from /api/v1/health or /api/v1/stats"
        raise ValueError(msg)
    return health_body, stats_body


def _format_uptime(seconds: float) -> str:
    """Format a duration as ``HHh MMm SSs`` with zero-padded fields."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}h {minutes:02d}m {secs:02d}s"


def _format_severity(breakdown: dict[str, int]) -> str:
    """Format ``{critical: 4, high: 18}`` as ``critical=4 high=18`` (severity-order)."""
    # Deterministic order: highest severity first when keys are well-known,
    # else fall back to alphabetical so tests stay stable.
    order = ["critical", "high", "medium", "low", "info"]
    known = [k for k in order if k in breakdown]
    extra = sorted(k for k in breakdown if k not in order)
    return " ".join(f"{k}={breakdown[k]}" for k in (*known, *extra))


def format_human(health: dict[str, Any], stats: dict[str, Any]) -> str:
    """Render the human-readable status block.

    Output is two aligned columns: label + value, padded to a common label
    width so each row reads as a key/value pair. Components follow on
    indented lines so they visually belong to the ``components`` heading.
    """
    status = str(health.get("status", "unknown"))

    summary_rows: list[tuple[str, str]] = [
        ("uptime", _format_uptime(float(stats.get("uptime_seconds", 0.0)))),
        (
            "event_rate",
            f"{float(stats.get('event_rate_per_sec', 0.0)):.2f} events/sec",
        ),
        ("total_events", f"{int(stats.get('total_events', 0)):,}"),
        ("total_alerts", f"{int(stats.get('total_alerts', 0)):,}"),
        ("active_sources", str(int(stats.get("active_sources", 0)))),
        ("model_count", str(int(stats.get("model_count", 0)))),
        (
            "alerts_by_severity",
            _format_severity(dict(stats.get("alerts_by_severity") or {})),
        ),
    ]

    components: dict[str, str] = dict(health.get("components") or {})

    # Compute a label width that fits both summary keys and component names
    # so the value column lines up across both blocks.
    label_width = max(
        (len(label) for label, _ in summary_rows),
        default=0,
    )
    label_width = max(label_width, *(len(name) for name in components), 16)

    summary_lines = [f"{label:<{label_width}}  {value}" for label, value in summary_rows]
    # Indent component rows by two spaces — same visual convention as the
    # other Seerflow CLI subcommands (e.g. ``seerflow query``).
    component_lines = [f"  {name:<{label_width}}{components[name]}" for name in sorted(components)]

    sections: list[str] = [
        f"Status: {status}",
        "",
        *summary_lines,
        "",
        "components",
        *component_lines,
    ]
    return "\n".join(sections) + "\n"


def format_json(health: dict[str, Any], stats: dict[str, Any]) -> str:
    """Render the machine-readable status document.

    Merges ``/api/v1/health`` and ``/api/v1/stats`` verbatim and lifts
    ``health.status`` to the top level so consumers can read a single
    ``status`` field without re-deriving it.
    """
    merged: dict[str, Any] = {"status": health.get("status")}
    # ``stats`` first so it provides defaults; ``health`` overlays its
    # richer ``components`` / ``detection`` / ``feedback`` keys on top.
    merged.update(stats)
    merged.update(health)
    return json.dumps(merged, sort_keys=False, indent=2)


def _emit_unreachable_hint(host: str, port: int, reason: str) -> None:
    """Write the operator hint to stderr (used when the daemon is unreachable)."""
    msg = (
        f"seerflow status: cannot reach API at http://{host}:{port} ({reason}). "
        "Is 'seerflow start' running? Check 'dashboard_port' and "
        "'health_bind_address' in your config."
    )
    print(msg, file=sys.stderr)


async def run_status(args: argparse.Namespace) -> int:
    """Entry point invoked by ``seerflow status``.

    Returns ``0`` healthy, ``2`` degraded, ``3`` unreachable.
    """
    host, port = _load_endpoint(args)
    timeout = float(getattr(args, "timeout", _REQUEST_TIMEOUT_DEFAULT_S))
    try:
        health, stats = await _fetch(host, port, timeout)
    except (httpx.HTTPError, ValueError) as exc:
        _emit_unreachable_hint(host, port, type(exc).__name__)
        return EXIT_UNREACHABLE

    if getattr(args, "json", False):
        print(format_json(health, stats))
    else:
        print(format_human(health, stats), end="")

    return EXIT_DEGRADED if health.get("status") == "degraded" else EXIT_HEALTHY


__all__ = [
    "EXIT_DEGRADED",
    "EXIT_HEALTHY",
    "EXIT_UNREACHABLE",
    "format_human",
    "format_json",
    "run_status",
]
