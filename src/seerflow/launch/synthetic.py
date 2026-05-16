"""Deterministic synthetic syslog generator for the launch kit (S-090).

Owns its own seeded generator -- ``tests/`` is not an installed package, so
the launch kit cannot import ``tests/benchmarks/profile_pipeline.py``. Same
event family, deterministic for a fixed seed (byte-stable), so benchmark and
demo runs are reproducible.
"""

from __future__ import annotations

import random

from seerflow.receivers.base import RawEvent

_TEMPLATES: tuple[str, ...] = (
    "Accepted password for {user} from {ip} port {port} ssh2",
    "Failed password for {user} from {ip} port {port} ssh2",
    "error: maximum authentication attempts exceeded for {user} from {ip}",
    "GET /api/v1/{path} HTTP/1.1 200 {ms}ms",
    "POST /api/v1/{path} HTTP/1.1 201 {ms}ms",
    "CRON[{pid}]: ({user}) CMD ({cmd})",
    "systemd[1]: Started {service}.service",
    "Out of memory: Killed process {pid} ({proc})",
)
_USERS = ("admin", "root", "deploy", "www-data", "jenkins", "ubuntu")
_HOSTS = ("web-01", "web-02", "db-01", "app-01", "worker-03", "cache-01")
_PATHS = ("health", "users", "events", "metrics", "status", "logs")
_SERVICES = ("nginx", "postgresql", "redis", "celery", "gunicorn")
_CMDS = ("/usr/bin/logrotate /etc/logrotate.conf", "/opt/backup.sh", "sync")
_PROCS = ("java", "python3", "node", "redis-server", "postgres")


def build_events(n: int, *, seed: int = 42) -> list[RawEvent]:
    """Create ``n`` deterministic syslog ``RawEvent`` objects.

    Same ``seed`` -> byte-identical payloads (reproducible benchmark/demo).
    """
    rng = random.Random(seed)  # noqa: S311 -- not cryptographic
    base_ns = 1_710_000_000_000_000_000
    events: list[RawEvent] = []
    for i in range(n):
        body = rng.choice(_TEMPLATES).format(
            user=rng.choice(_USERS),
            ip=f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
            port=rng.randint(1024, 65535),
            path=rng.choice(_PATHS),
            ms=rng.randint(1, 500),
            pid=rng.randint(1000, 99999),
            cmd=rng.choice(_CMDS),
            service=rng.choice(_SERVICES),
            proc=rng.choice(_PROCS),
        )
        pri = rng.choice((134, 131, 139, 133, 132))
        hh, mm, ss = rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)
        host = rng.choice(_HOSTS)
        message = (
            f"<{pri}>1 2026-03-28T{hh:02d}:{mm:02d}:{ss:02d}Z "
            f"{host} sshd {rng.randint(100, 99999)} - - {body}"
        )
        events.append(
            RawEvent(
                data=message.encode(),
                source_type="syslog",
                source_id="launch-synthetic",
                received_ns=base_ns + i * 1_000_000,
                metadata={},
            )
        )
    return events
