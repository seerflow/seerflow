"""Shared test helpers for Seerflow tests."""

from __future__ import annotations

import ast
import inspect
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any

from seerflow.models.event import SeerflowEvent, SeverityLevel


def make_event(
    *,
    message: str = "test event",
    severity: SeverityLevel = SeverityLevel.INFORMATIONAL,
    entity_refs: tuple[str, ...] = (),
    source_type: str = "test",
    source_id: str = "test",
    log_source_category: str = "",
    log_source_product: str = "",
    log_source_service: str = "",
    related_ips: tuple[str, ...] = (),
    related_users: tuple[str, ...] = (),
    related_hosts: tuple[str, ...] = (),
    related_hashes: tuple[str, ...] = (),
    related_domains: tuple[str, ...] = (),
    related_files: tuple[str, ...] = (),
    related_processes: tuple[str, ...] = (),
    template_id: int = -1,
    template_str: str = "",
    event_id: uuid.UUID | None = None,
    timestamp_ns: int | None = None,
    event_kind: str = "event",
    event_category: str = "",
    event_type: str = "",
    event_action: str = "",
    event_outcome: str = "",
) -> SeerflowEvent:
    """Create a minimal SeerflowEvent with sensible defaults for testing."""
    now_ns = timestamp_ns if timestamp_ns is not None else time.time_ns()
    return SeerflowEvent(
        event_id=event_id if event_id is not None else uuid.uuid4(),
        timestamp_ns=now_ns,
        observed_ns=now_ns + 1_000_000,
        severity_id=severity,
        message=message,
        source_type=source_type,
        source_id=source_id,
        log_source_category=log_source_category,
        log_source_product=log_source_product,
        log_source_service=log_source_service,
        entity_refs=entity_refs,
        related_ips=related_ips,
        related_users=related_users,
        related_hosts=related_hosts,
        related_hashes=related_hashes,
        related_domains=related_domains,
        related_files=related_files,
        related_processes=related_processes,
        template_id=template_id,
        template_str=template_str,
        event_kind=event_kind,
        event_category=event_category,
        event_type=event_type,
        event_action=event_action,
        event_outcome=event_outcome,
    )


def module_source_text(obj: Any) -> str:
    """Return the full Python source of ``obj``'s defining module.

    Uses :func:`inspect.getfile` + :meth:`pathlib.Path.read_text` instead of
    :func:`inspect.getsource` so the call does not depend on the CPython
    ``linecache``. Closes the ``OSError: could not get source code`` flake
    class tracked by SEE-214 (S-193) and SEE-215 (S-224).
    """
    return Path(inspect.getfile(obj)).read_text(encoding="utf-8")


def function_source_text(obj: Any, qualname: str | None = None) -> str:
    """Return the raw source text of a function or method, dedented to column 0.

    The snippet is sliced from the original module source by line numbers from
    a fresh :func:`ast.parse`, so original whitespace, blank lines, and comments
    are preserved verbatim. This matters for callers that re-parse the result
    and assert on line spans (e.g. ``TestEnsembleFunctionLength`` in
    ``tests/unit/test_detection_ensemble.py``).

    ``qualname`` defaults to ``obj.__qualname__`` and is used to walk the AST
    when the target is a method on a class (e.g.
    ``DetectionEnsemble._load_granular_hw``).
    """
    raw = module_source_text(obj)
    target = qualname or getattr(obj, "__qualname__", None)
    if target is None:
        raise TypeError(f"cannot infer qualname for {obj!r}; pass qualname= explicitly")
    node = _find_function_node(ast.parse(raw), target)
    lines = raw.splitlines(keepends=True)
    snippet = "".join(lines[node.lineno - 1 : node.end_lineno])
    return textwrap.dedent(snippet)


def _find_function_node(tree: ast.AST, qualname: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Walk ``tree`` for the dotted ``qualname`` and return the function node."""
    parts = qualname.split(".")
    nodes: list[ast.AST] = list(ast.iter_child_nodes(tree))
    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        for node in nodes:
            if (
                isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == part
            ):
                if is_last:
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        raise TypeError(f"{qualname} resolves to a class, not a function")
                    return node
                nodes = list(ast.iter_child_nodes(node))
                break
        else:
            raise ValueError(f"could not resolve {qualname} in module source")
    raise ValueError(f"could not resolve {qualname}")
