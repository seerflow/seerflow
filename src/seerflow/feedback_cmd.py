"""CLI handler for 'seerflow feedback' command."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from seerflow.storage import connect_storage

if TYPE_CHECKING:
    import argparse

_log = logging.getLogger("seerflow")


async def run_feedback(args: argparse.Namespace) -> None:
    """Run the feedback command."""
    from seerflow.alerting.feedback import process_feedback
    from seerflow.config import load_config
    from seerflow.detection.ensemble import DetectionEnsemble

    from seerflow.utils.text import sanitise_feedback_note

    safe_note = ""
    if args.note:
        safe_note = sanitise_feedback_note(args.note)
        _log.info("Persisting feedback note (%d chars)", len(safe_note))

    config = load_config(args.config)
    storage = await connect_storage(config.storage)
    try:
        ensemble = DetectionEnsemble(config.detection)
        loaded = await ensemble.load_all_state(storage)
        _log.info("Loaded %d model states", loaded)

        try:
            result = await process_feedback(
                alert_id=args.alert_id,
                feedback=args.type,
                storage=storage,
                ensemble=ensemble,
                pagerduty_routing_key=config.alerting.pagerduty_routing_key,
                note=safe_note,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)  # noqa: T201
            sys.exit(1)
        print(result)  # noqa: T201

        saved = await ensemble.save_all_state(storage)
        _log.info("Saved %d model states", saved)
    finally:
        await storage.close()
