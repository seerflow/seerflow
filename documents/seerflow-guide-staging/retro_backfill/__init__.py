"""EPIC-DOC retrospective backfill helpers (S-180-F3).

Pure helpers that turn pre-fetched Linear issue dicts into the actual-points
+ cycle-time rows that fill in the ``TBD`` cells of
``guide/retros/epic-doc-2026-04.md``. The Linear MCP fetch itself stays in the
agent session — these helpers are unit-tested with synthetic fixtures so CI
does not require Linear access.
"""
