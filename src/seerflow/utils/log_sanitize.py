"""Secret-redacting exception → string helper (S-080).

Strips connection-string credentials (PostgreSQL DSN userinfo, ``password=``
key-values, ``dsn=`` key-values) from exception messages before they reach
log handlers. Built to address an S-056 code-review finding: ``asyncpg``
exceptions can embed the full DSN (including password) in ``args`` or in
the ``__cause__`` chain, so ``_log.warning("...", exc_info=True)`` would
otherwise leak credentials to whatever log sink is attached.

Use ``sanitize_exception(exc)`` in place of ``exc_info=True`` for any log
site that may observe a storage-layer exception.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["sanitize_exception"]

_MAX_CAUSE_DEPTH: Final[int] = 2

# ``postgres://user:pass@host`` or ``postgresql://user:pass@host`` -> mask userinfo.
_DSN_USERINFO_RE = re.compile(r"(postgres(?:ql)?://)[^@\s]+@")
# ``password=secret`` / ``password : secret`` / ``Password=secret`` -> mask value.
_PASSWORD_KV_RE = re.compile(r"(password\s*[:=]\s*)\S+", re.IGNORECASE)
# ``dsn=postgresql://...`` -> mask the whole value token.
_DSN_KV_RE = re.compile(r"(dsn\s*[:=]\s*)\S+", re.IGNORECASE)


def _scrub(text: str) -> str:
    """Apply all redactions to ``text``. Order matters: DSN-kv first."""
    out = _DSN_KV_RE.sub(r"\1***", text)
    out = _DSN_USERINFO_RE.sub(r"\1***@", out)
    out = _PASSWORD_KV_RE.sub(r"\1***", out)
    return out


def _stringify(value: object) -> str:
    """Best-effort ``str(value)`` that never raises."""
    try:
        return str(value)
    except Exception:  # pragma: no cover - extremely defensive
        return repr(value)


def sanitize_exception(exc: BaseException) -> str:
    """Return a redacted, single-line summary of ``exc`` (and its causes).

    Walks ``exc.args`` plus up to :data:`_MAX_CAUSE_DEPTH` ``__cause__``
    links, ``str()``-ifies each part, and runs the result through the DSN /
    password / dsn-kv regex chain. Output is comma-joined so log handlers
    keep the record on one line.
    """
    parts: list[str] = []
    cursor: BaseException | None = exc
    depth = 0
    while cursor is not None and depth <= _MAX_CAUSE_DEPTH:
        parts.append(_stringify(cursor))
        if cursor.args:
            for arg in cursor.args:
                rendered = _stringify(arg)
                if rendered not in parts[-1]:
                    parts.append(rendered)
        cursor = cursor.__cause__
        depth += 1

    joined = "; ".join(p for p in parts if p)
    return _scrub(joined)
