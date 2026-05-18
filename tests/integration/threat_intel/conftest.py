"""S-238 (SEE-251): single autouse DNS-guard bypass for threat-intel
integration tests.

The bypass logic lives once in ``tests.helpers.apply_dns_guard_bypass``.
No whitelist is needed here — no real-resolver test lives in this package
(those are in ``tests/unit/threat_intel/test_dns.py`` and
``tests/unit/test_threat_intel_config.py``).
"""

from __future__ import annotations

import pytest

from tests.helpers import apply_dns_guard_bypass


@pytest.fixture(autouse=True)
def _bypass_dns_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    apply_dns_guard_bypass(monkeypatch)
