"""CLI handler for ``seerflow templates list|prune|reset`` (S-077, FR-045).

Drain3 template management:

- ``list``  — read-only print of the persisted ``templates`` table.
- ``prune`` — delete rows with ``event_count < min_count``.
- ``reset`` — wipe every row **and** delete the persisted Drain3 model
  state (``drain3:global`` in ``model_state``) so the next pipeline
  startup rebuilds a fresh template miner.

Destructive operations confirm interactively unless ``--yes`` is passed.
Non-TTY stdin without ``--yes`` rejects the operation with exit code 2
to avoid silently wiping data from cron/CI.
"""
# ruff: noqa: T201 — print() is the correct output mechanism for CLI commands.

from __future__ import annotations

import logging
import sys
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any, TextIO

import msgspec.json

from seerflow.cli_format import format_table
from seerflow.config import load_config
from seerflow.query import format_timestamp
from seerflow.storage import connect_storage

if TYPE_CHECKING:
    import argparse

    from seerflow.storage.factory import StorageBackend
    from seerflow.storage.sqlite import TemplateInfo


_log = logging.getLogger("seerflow")

_DRAIN_STATE_KEY = "drain3:global"
"""Key under which Drain3 persists its serialized parse tree."""

_DEFAULT_LIST_LIMIT = 100
"""Default ``--limit`` for the ``list`` subcommand."""

_MAX_LIST_LIMIT = 10_000
"""Hard cap on ``--limit`` to mirror the storage layer."""

_TEMPLATE_DISPLAY_WIDTH = 80
"""Truncate ``template_str`` to this width in the table view."""


# ---------------------------------------------------------------------------
# Helpers (small + testable)
# ---------------------------------------------------------------------------


def _isatty() -> bool:
    """Whether stdin is attached to a TTY.

    Wrapped for test injection. Catches ``AttributeError`` (some test
    doubles do not implement ``isatty()``) and ``OSError`` (closed or
    detached stdin in a forked subprocess) — both must not crash the
    confirmation gate.
    """
    try:
        return sys.stdin.isatty()
    except (AttributeError, OSError):
        return False


def _read_confirmation_input(stdin: TextIO) -> str:
    """Read one line from *stdin* and strip the trailing newline.

    Wrapped so tests can patch the read without having to attach a real
    pseudo-TTY.
    """
    return stdin.readline().strip()


def _confirm(
    prompt: str,
    *,
    yes: bool,
    stdin: TextIO,
    stdout: TextIO,
) -> bool:
    """Interactive ``[y/N]`` confirmation.

    Behaviour:
    - ``yes=True`` short-circuits to ``True`` (no prompt, no read).
    - Non-TTY stdin without ``--yes`` returns ``False`` — refuses to run
      destructive commands in CI / piped contexts.
    - Otherwise read a line; ``y``/``yes`` (case-insensitive) accepts,
      everything else rejects.
    """
    if yes:
        return True
    if not _isatty():
        return False
    stdout.write(f"{prompt} [y/N]: ")
    stdout.flush()
    answer = _read_confirmation_input(stdin).lower()
    return answer in {"y", "yes"}


async def _connect_storage_from_args(args: argparse.Namespace) -> StorageBackend:
    """Resolve config and connect to storage. Wrapped for test injection."""
    config = load_config(args.config)
    return await connect_storage(config.storage)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def _template_to_json_dict(t: TemplateInfo) -> dict[str, Any]:
    return {
        "template_id": t.template_id,
        "event_count": t.event_count,
        "first_seen": format_timestamp(t.first_seen_ns),
        "last_seen": format_timestamp(t.last_seen_ns),
        "template": t.template_str,
    }


async def run_templates_list(
    storage: StorageBackend,
    args: argparse.Namespace,
) -> int:
    """Render the templates table to stdout.

    Pre-conditions (validated by the caller / dispatcher): ``args.limit``
    is an int in ``[1, _MAX_LIST_LIMIT]``.
    """
    templates = await storage.get_templates(limit=args.limit)

    if not templates:
        print("No templates found.")
        return 0

    if args.json:
        encoded = msgspec.json.encode([_template_to_json_dict(t) for t in templates])
        sys.stdout.buffer.write(encoded)
        print()
        return 0

    headers = ["TID", "COUNT", "FIRST SEEN", "LAST SEEN", "TEMPLATE"]
    rows = [
        [
            str(t.template_id),
            str(t.event_count),
            format_timestamp(t.first_seen_ns),
            format_timestamp(t.last_seen_ns),
            t.template_str[:_TEMPLATE_DISPLAY_WIDTH],
        ]
        for t in templates
    ]
    print(format_table(headers, rows), end="")
    print(f"\n{len(templates)} template(s)")
    return 0


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


def _emit_destructive_refusal() -> None:
    print(
        "Error: refusing to run destructive command on non-TTY stdin without --yes. "
        "Pass --yes to confirm.",
        file=sys.stderr,
    )


async def run_templates_prune(
    storage: StorageBackend,
    args: argparse.Namespace,
) -> int:
    """Delete templates with ``event_count < args.min_count``.

    Pre-conditions (validated by the caller / dispatcher):
    ``args.min_count`` is an int >= 0.
    """
    min_count = args.min_count

    if not args.yes and not _isatty():
        _emit_destructive_refusal()
        return 2

    if not _confirm(
        f"Prune templates with event_count < {min_count}?",
        yes=args.yes,
        stdin=sys.stdin,
        stdout=sys.stdout,
    ):
        print("Cancelled.")
        return 0

    deleted = await storage.prune_templates(min_count)
    remaining = len(await storage.get_templates(limit=_MAX_LIST_LIMIT))

    if args.json:
        sys.stdout.buffer.write(msgspec.json.encode({"deleted": deleted, "remaining": remaining}))
        print()
    else:
        print(f"Pruned {deleted} template(s); {remaining} remaining.")
    return 0


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


async def run_templates_reset(
    storage: StorageBackend,
    args: argparse.Namespace,
) -> int:
    """Wipe the templates table and the persisted Drain3 model state."""
    if not args.yes and not _isatty():
        _emit_destructive_refusal()
        return 2

    if not _confirm(
        "Reset all Drain3 templates AND clear persisted parser state?",
        yes=args.yes,
        stdin=sys.stdin,
        stdout=sys.stdout,
    ):
        print("Cancelled.")
        return 0

    state_present_before = await storage.load_state(_DRAIN_STATE_KEY) is not None
    if state_present_before:
        await storage.delete_state(_DRAIN_STATE_KEY)
    deleted = await storage.reset_templates()

    if args.json:
        sys.stdout.buffer.write(
            msgspec.json.encode(
                {
                    "deleted_templates": deleted,
                    "drain_state_cleared": state_present_before,
                }
            )
        )
        print()
    else:
        suffix = " and cleared Drain3 state" if state_present_before else ""
        print(f"Reset {deleted} template(s){suffix}.")
    return 0


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


_SUBCOMMANDS = {"list", "prune", "reset"}


async def run_templates(args: argparse.Namespace) -> int:
    """Top-level dispatcher for ``seerflow templates …``.

    Returns a process exit code:
        0 — success
        1 — runtime / storage error
        2 — argument-validation error
    """
    sub = getattr(args, "templates_cmd", None)
    if sub not in _SUBCOMMANDS:
        print(
            f"Error: unknown templates subcommand {sub!r}. "
            f"Expected one of: {', '.join(sorted(_SUBCOMMANDS))}.",
            file=sys.stderr,
        )
        return 2

    # Early validation for list/prune — avoid an unnecessary storage
    # connection when the user passed bad args.
    if sub == "list":
        limit = getattr(args, "limit", None)
        if limit is None or limit < 1 or limit > _MAX_LIST_LIMIT:
            print(
                f"Error: --limit must be between 1 and {_MAX_LIST_LIMIT}, got {limit!r}",
                file=sys.stderr,
            )
            return 2
    elif sub == "prune":
        min_count = getattr(args, "min_count", None)
        if min_count is None or min_count < 0:
            print(
                f"Error: --min-count must be >= 0, got {min_count!r}",
                file=sys.stderr,
            )
            return 2

    storage = await _connect_storage_from_args(args)
    async with AsyncExitStack() as stack:
        stack.push_async_callback(storage.close)
        try:
            if sub == "list":
                return await run_templates_list(storage, args)
            if sub == "prune":
                return await run_templates_prune(storage, args)
            return await run_templates_reset(storage, args)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            _log.exception("templates %s failed", sub)
            return 1
    return 0  # pragma: no cover — AsyncExitStack always exits via return


__all__ = [
    "run_templates",
    "run_templates_list",
    "run_templates_prune",
    "run_templates_reset",
]
