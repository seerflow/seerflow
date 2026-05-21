"""Integration test for the S-308 LANL fetch tool (SEE-271 / FR-076).

Exercises the real end-to-end contract with **no network**: an in-memory
fake transport serves gzip-compressed members; ``fetch_dataset`` downloads,
SHA-256-verifies, and decompresses them; then the produced directory is fed
to the *real* ``seerflow.lanl`` CSV parsers to prove the output layout is
exactly what the validator consumes (``auth.csv / proc.csv / flows.csv /
redteam.csv``).

This is the cross-component boundary that matters for FR-076: the fetch
tool's job is only done if its output is directly parseable by the existing
LANL validation pipeline.
"""

from __future__ import annotations

import gzip
import hashlib
from typing import TYPE_CHECKING

from seerflow.lanl import fetch as fetch_mod
from seerflow.lanl.parser import (
    parse_auth_line,
    parse_flow_line,
    parse_proc_line,
    parse_redteam_line,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# One valid CSV row per member, in the published LANL column order the
# existing parsers expect.
_ROWS = {
    "auth": "1,U1@DOM1,U1@DOM1,C1,C2,Negotiate,Network,LogOn,Success",
    "proc": "1,U1@DOM1,C1,proc.exe,Start",
    "flows": "1,1,C1,80,C2,443,6,5,1024",
    "redteam": "1,U1@DOM1,C1,C2",
}


class _FakeTransport:
    """In-memory transport — the only "network" in this integration test."""

    def __init__(self, bodies: dict[str, bytes]) -> None:
        self._bodies = bodies

    def head(self, url: str) -> tuple[int, bool]:
        return len(self._bodies[url]), True

    def get(self, url: str, start_byte: int) -> Iterator[bytes]:
        yield self._bodies[url][start_byte:]


def test_fetch_output_is_consumed_by_real_lanl_parsers(tmp_path: Path) -> None:
    base = "https://fake.invalid/"
    members = []
    bodies: dict[str, bytes] = {}
    for name in ("auth", "proc", "flows", "redteam"):
        plain = (_ROWS[name] + "\n").encode()
        gz = gzip.compress(plain)
        url = f"{base}{name}.txt.gz"
        bodies[url] = gz
        members.append(
            fetch_mod.LanlMember(
                name=name,
                remote=url,
                csv_name=f"{name}.csv",
                size=len(gz),
                sha256=hashlib.sha256(gz).hexdigest(),
            )
        )
    manifest = fetch_mod.LanlManifest(base_url=base, members=tuple(members))

    fetch_mod.fetch_dataset(tmp_path, transport=_FakeTransport(bodies), manifest=manifest)

    # The decompressed directory must match the validator's contract exactly
    # and every file must parse with the real (untouched) LANL parsers.
    auth = parse_auth_line((tmp_path / "auth.csv").read_text().strip())
    assert auth.src_computer == "C1"
    assert auth.success is True

    proc = parse_proc_line((tmp_path / "proc.csv").read_text().strip())
    assert proc.computer == "C1"

    flow = parse_flow_line((tmp_path / "flows.csv").read_text().strip())
    assert flow.src_computer == "C1"

    rt = parse_redteam_line((tmp_path / "redteam.csv").read_text().strip())
    assert rt.src_computer == "C1"


def test_fetch_corrupt_member_writes_no_csv(tmp_path: Path) -> None:
    """A bad checksum aborts before any CSV — nothing reaches the validator."""
    base = "https://fake.invalid/"
    members = []
    bodies: dict[str, bytes] = {}
    for name in ("auth", "proc", "flows", "redteam"):
        gz = gzip.compress((_ROWS[name] + "\n").encode())
        url = f"{base}{name}.txt.gz"
        bodies[url] = gz
        sha = hashlib.sha256(gz).hexdigest()
        if name == "flows":
            sha = "0" * 64  # poison one member
        members.append(
            fetch_mod.LanlMember(
                name=name,
                remote=url,
                csv_name=f"{name}.csv",
                size=len(gz),
                sha256=sha,
            )
        )
    manifest = fetch_mod.LanlManifest(base_url=base, members=tuple(members))

    raised = False
    try:
        fetch_mod.fetch_dataset(tmp_path, transport=_FakeTransport(bodies), manifest=manifest)
    except fetch_mod.DatasetVerificationError:
        raised = True

    assert raised, "corrupt member must fail loudly"
    for name in ("auth", "proc", "flows", "redteam"):
        assert not (tmp_path / f"{name}.csv").exists()
