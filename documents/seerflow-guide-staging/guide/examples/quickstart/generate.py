#!/usr/bin/env python3
"""Generate a deterministic 20-line OpenTelemetry sample log dump.

Run from this directory with ``python generate.py``; it overwrites
``sample-logs.jsonl`` in place. The script is committed alongside the JSONL so
contributors can regenerate the fixture if upstream schema needs change.

The dump contains:

* 15 lines of nominal info/debug traffic from a fake API service, with
  monotonically increasing nanosecond timestamps.
* A 5-line error burst toward the end — the anomaly Seerflow's Half-Space
  Trees + volume Holt-Winters detectors should flag in the quickstart.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

_SEED = 42
_OUTPUT = Path(__file__).resolve().parent / "sample-logs.jsonl"
_BASE_TIME_NS = 1_715_000_000_000_000_000  # 2024-05-06T13:53:20Z (anchor only)


def _line(
    *,
    timestamp_ns: int,
    severity: int,
    severity_text: str,
    body: str,
    service: str = "checkout-api",
    user: str | None = None,
) -> dict[str, object]:
    """Build one OpenTelemetry-shaped LogRecord dict."""

    attrs: dict[str, object] = {"service.name": service}
    if user is not None:
        attrs["user.id"] = user
    return {
        "TimeUnixNano": timestamp_ns,
        "ObservedTimeUnixNano": timestamp_ns + 1_000,
        "SeverityNumber": severity,
        "SeverityText": severity_text,
        "Body": body,
        "Attributes": attrs,
    }


def build_lines() -> list[dict[str, object]]:
    """Return the deterministic 20-entry log dump as a list of dicts."""

    rng = random.Random(_SEED)  # noqa: S311 — deterministic synthetic fixture, not crypto
    users = ["alice", "bob", "carol", "dave"]
    lines: list[dict[str, object]] = []
    timestamp = _BASE_TIME_NS

    for _ in range(15):
        timestamp += rng.randint(100_000_000, 300_000_000)
        lines.append(
            _line(
                timestamp_ns=timestamp,
                severity=9,
                severity_text="INFO",
                body="GET /api/cart 200",
                user=rng.choice(users),
            )
        )

    # Error burst — drives the quickstart anomaly alert.
    for _ in range(5):
        timestamp += rng.randint(10_000_000, 20_000_000)
        lines.append(
            _line(
                timestamp_ns=timestamp,
                severity=17,
                severity_text="ERROR",
                body="POST /api/checkout 500 — payment-gateway timeout",
                user=rng.choice(users),
            )
        )
    return lines


def main() -> None:
    lines = build_lines()
    with _OUTPUT.open("w", encoding="utf-8") as fh:
        for record in lines:
            fh.write(json.dumps(record, sort_keys=True))
            fh.write("\n")
    print(f"Wrote {len(lines)} log lines to {_OUTPUT}")  # noqa: T201 — CLI feedback


if __name__ == "__main__":
    main()
