"""S-238 (SEE-251): single autouse DNS-guard bypass for tests/unit/threat_intel.

Replaces the four duplicated per-file ``_bypass_dns_guard`` fixtures S-227
introduced. The bypass logic lives once in
``tests.helpers.apply_dns_guard_bypass``.

``test_dns.py`` is whitelisted out: it exercises the *real*
``_resolve_feed_with_private_ip_guard`` SSRF guard (e.g.
``test_build_static_resolver_map_propagates_private_ip_rejection``) and
must NOT receive the bypass monkeypatch.
"""

from __future__ import annotations

import pytest

from tests.helpers import apply_dns_guard_bypass

# Modules in this package that intentionally exercise the REAL resolver and
# must NOT receive the bypass monkeypatch.
_REAL_RESOLVER_MODULES = frozenset({"test_dns.py"})


@pytest.fixture(autouse=True)
def _bypass_dns_guard(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    if request.path.name in _REAL_RESOLVER_MODULES:
        return
    apply_dns_guard_bypass(monkeypatch)
