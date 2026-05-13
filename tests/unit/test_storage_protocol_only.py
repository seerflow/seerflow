"""S-074 architectural guard: production code may not import concrete storage backends.

The storage layer offers two backends (``SqliteBackend``, ``PostgresBackend``)
behind a set of ``Protocol`` interfaces (``LogStore``, ``AlertStore``,
``ModelStore``, ``EntityStore``, ``GraphStore``, ``SigmaRuleStateStore``).
Application code (pipeline, API, CLI, detection, correlation) must depend on
the **Protocols** only, never on a concrete backend class — that is what
makes the ``storage.backend: sqlite | postgresql`` switch a one-line change.

This test AST-walks ``src/seerflow/`` and rejects any ``ImportFrom`` that
pulls a name from a concrete-backend module, except for the ``storage/``
sub-package itself (which is allowed to import its own siblings) and a
small allow-list of shared value types that legitimately live next to
the backend code (e.g. ``TemplateInfo``).

If a future PR breaks this guard, the right fix is almost always to move
the leaked symbol to ``seerflow.storage.protocols`` or ``seerflow.models.*``,
not to extend the allow-list.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src" / "seerflow"
STORAGE_ROOT = SRC_ROOT / "storage"

# Modules that hold *concrete* backend implementations. Production code
# outside ``seerflow.storage`` may not import names from these modules.
_CONCRETE_BACKEND_MODULES = frozenset(
    {
        "seerflow.storage.sqlite",
        "seerflow.storage.postgres",
        "seerflow.storage._sqlite_alerts",
        "seerflow.storage._postgres_alerts",
        "seerflow.storage._sqlite_sigma_state",
        "seerflow.storage._postgres_sigma_state",
        "seerflow.storage.postgres_migrations",
        "seerflow.storage.migrations",
        "seerflow.storage._mitre_backfill",
    }
)

# Allow-list of leaked-but-acceptable symbols. Each entry must justify why
# the symbol is in a backend module and why moving it out is not worth the
# churn. New entries require sign-off in code review.
#
# ``TemplateInfo`` is a ``msgspec.Struct`` shared by both backends to expose
# Drain3 template metadata to the pipeline handler. It is a pure value type
# (no backend coupling) that incidentally lives next to ``SqliteBackend`` for
# historical reasons. Moving it would touch both backends and is tracked as
# tech-debt; the allow-list keeps this guard meaningful in the meantime.
_ALLOW_LIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("seerflow.storage.sqlite", "TemplateInfo"),
    }
)


def _iter_production_py_files() -> list[Path]:
    """Return every ``.py`` file under ``src/seerflow/`` excluding ``storage/``."""
    return [
        path
        for path in SRC_ROOT.rglob("*.py")
        if STORAGE_ROOT not in path.parents and path != STORAGE_ROOT
    ]


def _collect_concrete_imports(path: Path) -> list[tuple[int, str, tuple[str, ...]]]:
    """Return ``(lineno, module, names)`` triples for concrete-backend imports.

    Imports under the ``_ALLOW_LIST`` are filtered out — they are accepted
    by policy. Any remaining triple is a guard violation.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[tuple[int, str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module not in _CONCRETE_BACKEND_MODULES:
            continue
        names = tuple(alias.name for alias in node.names)
        # Filter allow-listed (module, name) pairs out of the imported names.
        offenders = tuple(name for name in names if (node.module, name) not in _ALLOW_LIST)
        if offenders:
            violations.append((node.lineno, node.module, offenders))
    return violations


class TestStorageProtocolOnly:
    """Architectural guard for S-074."""

    def test_src_storage_subtree_exists(self) -> None:
        """Sanity: the AST walk would not silently pass if the tree moved."""
        assert SRC_ROOT.is_dir(), f"src tree missing: {SRC_ROOT}"
        assert STORAGE_ROOT.is_dir(), f"storage tree missing: {STORAGE_ROOT}"

    @pytest.mark.parametrize("path", _iter_production_py_files(), ids=lambda p: p.name)
    def test_no_concrete_backend_imports(self, path: Path) -> None:
        violations = _collect_concrete_imports(path)
        if violations:
            rendered = "\n".join(
                f"  {path}:{lineno}: from {module} import {', '.join(names)}"
                for lineno, module, names in violations
            )
            pytest.fail(
                "Production code outside src/seerflow/storage/ must depend on "
                "Protocols (LogStore, AlertStore, ModelStore, EntityStore, "
                "GraphStore, SigmaRuleStateStore), not on concrete backend "
                f"modules. Violations:\n{rendered}\n\n"
                "Fix: move the imported symbol to seerflow.storage.protocols "
                "(if it is part of the contract) or seerflow.models.* (if it "
                "is a value type), and update the import. If the symbol must "
                "stay in a backend module, add a justified entry to "
                "_ALLOW_LIST in this test."
            )

    def test_allow_list_entries_resolve(self) -> None:
        """Every allow-listed symbol must actually exist; stale entries rot the guard."""
        import importlib

        for module_name, symbol in _ALLOW_LIST:
            mod = importlib.import_module(module_name)
            assert hasattr(mod, symbol), (
                f"Allow-listed symbol does not exist: {module_name}.{symbol}. "
                "Remove the entry or fix the module."
            )
