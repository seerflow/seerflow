"""Deterministic narrated end-to-end demo (S-090).

Drives a short synthetic batch through the real pipeline and prints a
stable transcript (boot -> ingest -> detect -> alerts). Fast (<~10s),
side-effect-free (tempdir SQLite, cleaned up).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from seerflow.config import load_config
from seerflow.correlation.holders import EngineHolder
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.launch.synthetic import build_events
from seerflow.models.query import AlertQuery, EventQuery
from seerflow.pipeline.handler import make_handler
from seerflow.sigma.engine import SigmaEngine
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import Sequence


def _say(line: str) -> None:
    print(line)  # noqa: T201 -- CLI transcript is the contract


async def _demo(count: int, seed: int, data_dir: Path) -> int:
    _say("== Seerflow demo ==")
    _say("[1/4] boot: building pipeline (SQLite, ML ensemble, 63 Sigma rules)")
    cfg = data_dir / "seerflow.yaml"
    cfg.write_text(
        "storage:\n"
        f"  data_dir: {data_dir}\n"
        "receivers:\n"
        "  syslog_enabled: false\n"
        "  otlp_grpc_enabled: false\n"
        "  otlp_http_enabled: false\n"
        "  webhook_enabled: false\n"
    )
    config = load_config(str(cfg))
    storage = await SqliteBackend.connect(config.storage)
    ensemble = DetectionEnsemble(config.detection)
    sigma = SigmaEngine()
    sigma.load_bundled()
    handler = make_handler(
        ensemble,
        storage,
        save_interval_ns=999_999_999_999,
        sigma_holder=EngineHolder(engine=sigma),
    )
    try:
        events = build_events(count, seed=seed)
        _say(f"[2/4] ingest: feeding {count} synthetic syslog events")
        start = time.perf_counter()
        for event in events:
            await handler(event)  # type: ignore[operator]
        elapsed = time.perf_counter() - start
        await storage.flush()
        stored = (await storage.query_events(EventQuery(limit=1))).total
        alerts = (await storage.query_alerts(AlertQuery(limit=1))).total
        rate = stored / elapsed if elapsed > 0 else 0.0
        _say(
            f"[3/4] detect: {stored} events parsed + scored in "
            f"{elapsed:.2f}s ({rate:,.0f} ev/s)"
        )
        _say(f"[4/4] alerts: {alerts} alert(s) raised and persisted to SQLite")
        _say("Reproduce: python -m seerflow.launch.demo")
    finally:
        await storage.close()
    return 0


def run_demo(*, count: int = 400, seed: int = 7) -> int:
    """Run the demo in a tempdir; return process exit code."""
    with tempfile.TemporaryDirectory() as tmp:
        return asyncio.run(_demo(count, seed, Path(tmp)))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    p = argparse.ArgumentParser(
        prog="seerflow.launch.demo",
        description="Deterministic end-to-end Seerflow demo.",
    )
    p.add_argument("--count", type=int, default=400)
    p.add_argument("--seed", type=int, default=7)
    ns = p.parse_args(sys.argv[1:] if argv is None else argv)
    return run_demo(count=ns.count, seed=ns.seed)


if __name__ == "__main__":
    sys.exit(main())
