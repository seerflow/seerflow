"""Integration test for ``seerflow analyze`` full-stack path (S-303, FR-070).

Drives the real ``assemble_handler`` (S-302) through ``run_analyze`` over a
crafted log fixture and asserts the emitted NDJSON proves the *complete*
detection stack ran (correlation alerts that ``import``'s ML-only 2-arg
handler provably cannot produce), with the scriptable exit code — in one
step, no import->export round-trip.

Note on alert families: ``analyze`` tags events ``source_type="syslog"`` so
the bundled correlation ruleset (which the live syslog pipeline also uses)
fires identically — this is the FR-070 intent. Sigma's logsource-indexed
dispatch is normalizer-gated and the ML ensemble's anomaly flag is non-
deterministic on small synthetic input (both pre-existing, out-of-scope for
S-303 — see ``test_e2e_pipeline.py`` which asserts 0 sigma alerts today).
The robust, honest full-stack proof is therefore: *correlation alerts fire*
(impossible via ``import``) + non-zero exit code.
"""

from __future__ import annotations

import argparse
import io
import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def _ns(**kw: object) -> argparse.Namespace:
    base = {"paths": [], "output": None, "persist": False, "db": None, "config": None}
    base.update(kw)
    return argparse.Namespace(**base)


# A sustained ``Failed password`` SSH brute-force burst against one ip + user
# ending in a successful login drives the bundled ``credential-stuffing``
# rule (>=10 failed-password from one ip, syslog) and ``risk-accumulation``.
_BRUTE_FORCE = ["Failed password for user=root from 192.168.1.100 port 22 ssh2" for _ in range(40)]
_SUCCESS = [
    "Accepted password for user=root from 192.168.1.100 port 22 ssh2",
    "session opened for user=root by (uid=0)",
]
_ATTACK_LINES = "\n".join(_BRUTE_FORCE + _SUCCESS)

# Alert families a 2-arg ``make_handler(ensemble, storage)`` (what
# ``seerflow import`` uses) could ever emit. ``analyze`` must exceed this.
_IMPORT_ONLY_FAMILIES = {"ml"}


async def test_analyze_emits_correlation_and_nonzero_exit(tmp_path: Path) -> None:
    """The full stack runs: correlation alerts fire (import cannot) + exit 1."""
    from seerflow.analyze_cmd import run_analyze

    log = tmp_path / "attack.log"
    log.write_text(_ATTACK_LINES + "\n")
    out = tmp_path / "alerts.ndjson"

    rc = await run_analyze(_ns(paths=[str(log)], output=str(out)))

    lines = [json.loads(x) for x in out.read_text().splitlines() if x.strip()]
    types = {a["type"] for a in lines}
    assert lines, "expected at least one alert from the full detection stack"
    assert rc == 1, "exit code must be non-zero when >=1 alert fired"
    # FR-070 core: the *complete* stack ran, not import's ML-only subset.
    # A correlation alert is impossible through make_handler(ensemble,
    # storage) — its presence is definitive proof the Sigma/correlation/
    # UEBA/IoC engines were wired by assemble_handler.
    assert "correlation" in types, f"expected a correlation alert, got {types}"
    assert types - _IMPORT_ONLY_FAMILIES, (
        f"analyze must emit families beyond import's ML-only path, got {types}"
    )
    # NDJSON shape: one valid JSON object per line, export_cmd-compatible.
    sample = lines[0]
    assert {"alert_id", "type", "score", "timestamp_ns"} <= sample.keys()


async def test_analyze_zero_alerts_exit_zero(tmp_path: Path) -> None:
    """A benign single line fires nothing → empty NDJSON, exit 0."""
    from seerflow.analyze_cmd import run_analyze

    log = tmp_path / "benign.log"
    log.write_text("just one perfectly benign informational line\n")
    out = tmp_path / "b.ndjson"

    rc = await run_analyze(_ns(paths=[str(log)], output=str(out)))
    assert rc == 0
    assert out.read_text() == ""


async def test_analyze_no_persist_writes_nothing_to_disk(tmp_path: Path) -> None:
    from seerflow.analyze_cmd import run_analyze

    log = tmp_path / "a.log"
    log.write_text(_ATTACK_LINES + "\n")
    db = tmp_path / "should_not_exist.db"
    out = tmp_path / "o.ndjson"

    await run_analyze(_ns(paths=[str(log)], output=str(out), persist=False, db=str(db)))
    assert not db.exists(), "--no-persist must not create the configured db file"


async def test_analyze_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from seerflow.analyze_cmd import run_analyze

    monkeypatch.setattr("sys.stdin", io.StringIO(_ATTACK_LINES + "\n"))
    out = tmp_path / "s.ndjson"
    rc = await run_analyze(_ns(paths=["-"], output=str(out)))
    assert rc == 1, "stdin attack burst must fire correlation alerts (exit 1)"
    lines = [json.loads(x) for x in out.read_text().splitlines() if x.strip()]
    assert {a["type"] for a in lines} & {"correlation"}


async def test_analyze_persist_writes_to_db(tmp_path: Path) -> None:
    from seerflow.analyze_cmd import run_analyze

    log = tmp_path / "p.log"
    log.write_text(_ATTACK_LINES + "\n")
    db = tmp_path / "persisted.db"
    out = tmp_path / "p.ndjson"

    rc = await run_analyze(_ns(paths=[str(log)], output=str(out), persist=True, db=str(db)))
    assert rc == 1
    assert db.exists(), "--persist must create the configured db file"
