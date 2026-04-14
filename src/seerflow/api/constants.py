"""Cross-cutting numeric constants for the Seerflow REST API (S-187).

This module hosts stable, hard-coded API-layer caps that need to be
imported from both production code and tests. Keep it free of runtime
behaviour: no imports of ``seerflow.config``, no FastAPI state, no I/O.

Adding a new entry here is appropriate when the value is:

* a hard-coded safety ceiling (not an operator-tunable knob),
* referenced by more than one module,
* unrelated to the throttle / CORS concerns already owned by
  ``seerflow.api.limits``.
"""

from __future__ import annotations

# Upper bound for a single coverage scan. Matches ``AlertQuery.limit``
# ceiling; one SQL query replaces the former 10-page x 1_000-row loop.
# See ``seerflow.api.routes.attack._scan_alerts`` for the consumer.
MAX_ALERT_SCAN: int = 10_000
