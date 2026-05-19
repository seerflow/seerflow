"""Unit tests for the S-308 LANL fetch + verify tool.

The implementation lives in the tracked package module
:mod:`seerflow.lanl.fetch` (the ``scripts/fetch_lanl.py`` CLI shim is a thin
wrapper around it — ``scripts/`` is excluded from version control in this
repo, so the committable, coverage-gated code is the package module).

The tool downloads the LANL 2015 "Comprehensive, Multi-Source Cyber-Security
Events" release, SHA-256 verifies each member, resumes partial downloads via
HTTP ``Range``, and decompresses every ``*.txt.gz`` member into the
``auth.csv / proc.csv / flows.csv / redteam.csv`` layout that the existing
``seerflow.lanl`` validator consumes.

**No real network access happens here.** Every test injects an in-memory fake
``Transport`` so CI never touches ``csr.lanl.gov``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from seerflow.lanl import fetch as fetch_mod

if TYPE_CHECKING:
    from collections.abc import Iterator


def _load_module() -> object:
    """Return the tracked :mod:`seerflow.lanl.fetch` module under test."""
    return fetch_mod


# ---------------------------------------------------------------------------
# Fake transport — the only "network" in the whole suite.
# ---------------------------------------------------------------------------


class FakeTransport:
    """In-memory HTTP stand-in.

    ``bodies`` maps URL → raw bytes. Records every ``get`` call's start byte
    so resume behaviour can be asserted. ``chunk`` controls streaming
    granularity. ``truncate_at`` (if set, URL → int) forces a mid-stream
    failure after yielding that many bytes. ``supports_ranges`` toggles the
    ``Accept-Ranges`` advertisement (no-range server path).
    """

    def __init__(
        self,
        bodies: dict[str, bytes],
        *,
        chunk: int = 4,
        supports_ranges: bool = True,
        truncate_at: dict[str, int] | None = None,
    ) -> None:
        self.bodies = bodies
        self.chunk = chunk
        self.supports_ranges = supports_ranges
        self.truncate_at = truncate_at or {}
        self.get_calls: list[tuple[str, int]] = []
        self.head_calls: list[str] = []

    def head(self, url: str) -> tuple[int, bool]:
        self.head_calls.append(url)
        return len(self.bodies[url]), self.supports_ranges

    def get(self, url: str, start_byte: int) -> Iterator[bytes]:
        self.get_calls.append((url, start_byte))
        data = self.bodies[url]
        if not self.supports_ranges:
            start_byte = 0
        served = 0
        limit = self.truncate_at.get(url)
        for i in range(start_byte, len(data), self.chunk):
            piece = data[i : i + self.chunk]
            if limit is not None and served + len(piece) > limit:
                yield piece[: limit - served]
                raise ConnectionError(f"simulated truncation for {url}")
            served += len(piece)
            yield piece


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def mod() -> object:
    return _load_module()


@pytest.fixture
def fake_release() -> dict[str, dict[str, object]]:
    """Four tiny gzip members + their compressed bytes/sha/size."""
    raw = {
        "auth": b"1,U1@D1,U1@D1,C1,C2,Negotiate,Logon,LogOn,Success\n",
        "proc": b"1,U1@D1,C1,proc.exe,Start\n",
        "flows": b"1,1,C1,80,C2,443,6,5,1024\n",
        "redteam": b"1,U1@D1,C1,C2\n",
    }
    out: dict[str, dict[str, object]] = {}
    for name, plain in raw.items():
        gz = gzip.compress(plain)
        out[name] = {
            "plain": plain,
            "gz": gz,
            "sha256": _sha(gz),
            "size": len(gz),
        }
    return out


def _manifest_from(mod: object, fake: dict[str, dict[str, object]]) -> object:
    """Build a manifest object pointed at fake URLs matching ``fake``."""
    members = tuple(
        mod.LanlMember(  # type: ignore[attr-defined]
            name=name,
            remote=f"https://fake.invalid/{name}.txt.gz",
            csv_name=f"{name}.csv",
            size=int(fake[name]["size"]),  # type: ignore[arg-type]
            sha256=str(fake[name]["sha256"]),
        )
        for name in ("auth", "proc", "flows", "redteam")
    )
    return mod.LanlManifest(  # type: ignore[attr-defined]
        base_url="https://fake.invalid/",
        members=members,
    )


def _bodies(fake: dict[str, dict[str, object]]) -> dict[str, bytes]:
    return {
        f"https://fake.invalid/{name}.txt.gz": fake[name]["gz"]  # type: ignore[misc]
        for name in ("auth", "proc", "flows", "redteam")
    }


# ---------------------------------------------------------------------------
# Task 1 — module shape
# ---------------------------------------------------------------------------


def test_cli_shim_exists_and_delegates() -> None:
    """The AC-named ``scripts/fetch_lanl.py`` exists and wires to the module.

    ``scripts/`` is git-excluded in this repo, so the shim is local-only and
    asserted leniently — the committable contract is the package module.
    """
    shim = Path(__file__).resolve().parents[2] / "scripts" / "fetch_lanl.py"
    if shim.is_file():
        text = shim.read_text(encoding="utf-8")
        assert "from seerflow.lanl.fetch import main" in text
        assert "raise SystemExit(main())" in text


def test_module_runnable_as_main() -> None:
    """``python -m seerflow.lanl.fetch`` is wired (no real network)."""
    assert hasattr(fetch_mod, "main")


def test_module_imports_cleanly(mod: object) -> None:
    for attr in (
        "LANL_2015_MANIFEST",
        "LanlMember",
        "LanlManifest",
        "DatasetVerificationError",
        "Transport",
        "verify_member",
        "download_member",
        "unpack_member",
        "fetch_dataset",
        "main",
    ):
        assert hasattr(mod, attr), f"missing public symbol: {attr}"


def test_default_manifest_targets_2015_comprehensive(mod: object) -> None:
    man = mod.LANL_2015_MANIFEST  # type: ignore[attr-defined]
    assert "csr.lanl.gov/data/cyber1" in man.base_url
    names = {m.name for m in man.members}
    assert names == {"auth", "proc", "flows", "redteam"}
    for m in man.members:
        assert m.remote.endswith(".txt.gz")
        assert m.csv_name == f"{m.name}.csv"
        assert m.size > 0
        assert len(m.sha256) == 64


# ---------------------------------------------------------------------------
# Task 2 — verification (fail loudly, fail early)
# ---------------------------------------------------------------------------


def test_verify_member_passes_on_exact_file(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    member = man.members[0]
    p = tmp_path / "auth.txt.gz"
    p.write_bytes(fake_release["auth"]["gz"])  # type: ignore[arg-type]
    mod.verify_member(p, member)  # must not raise


def test_verify_member_missing_file_fails_loudly(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    with pytest.raises(mod.DatasetVerificationError, match="missing"):
        mod.verify_member(tmp_path / "nope.gz", man.members[0])


def test_verify_member_short_file_fails_loudly(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    p = tmp_path / "auth.txt.gz"
    p.write_bytes(fake_release["auth"]["gz"][:-3])  # type: ignore[index]
    with pytest.raises(mod.DatasetVerificationError, match="size"):
        mod.verify_member(p, man.members[0])


def test_verify_member_checksum_mismatch_fails_loudly(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    member = man.members[0]
    # Same size, different content → digest mismatch.
    p = tmp_path / "auth.txt.gz"
    p.write_bytes(b"\x00" * int(fake_release["auth"]["size"]))  # type: ignore[arg-type]
    with pytest.raises(mod.DatasetVerificationError, match=r"sha256|checksum"):
        mod.verify_member(p, member)


# ---------------------------------------------------------------------------
# Task 3 — resumable download
# ---------------------------------------------------------------------------


def test_download_full_then_atomic_rename(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    member = man.members[0]
    t = FakeTransport(_bodies(fake_release))
    mod.download_member(t, member, tmp_path)
    final = tmp_path / "auth.txt.gz"
    assert final.read_bytes() == fake_release["auth"]["gz"]
    assert not (tmp_path / "auth.txt.gz.part").exists()
    assert t.get_calls and t.get_calls[0][1] == 0


def test_download_resumes_from_partial(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    member = man.members[0]
    gz: bytes = fake_release["auth"]["gz"]  # type: ignore[assignment]
    part = tmp_path / "auth.txt.gz.part"
    part.write_bytes(gz[:5])  # 5 bytes already on disk
    t = FakeTransport(_bodies(fake_release))
    mod.download_member(t, member, tmp_path)
    assert (tmp_path / "auth.txt.gz").read_bytes() == gz
    # Only the missing tail must have been requested.
    assert t.get_calls[-1][1] == 5


def test_download_no_range_server_restarts_from_zero(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    member = man.members[0]
    gz: bytes = fake_release["auth"]["gz"]  # type: ignore[assignment]
    part = tmp_path / "auth.txt.gz.part"
    part.write_bytes(gz[:5])
    t = FakeTransport(_bodies(fake_release), supports_ranges=False)
    mod.download_member(t, member, tmp_path)
    assert (tmp_path / "auth.txt.gz").read_bytes() == gz
    assert t.get_calls[-1][1] == 0  # restarted from scratch


def test_download_truncation_keeps_part_and_no_final(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    member = man.members[0]
    t = FakeTransport(_bodies(fake_release), truncate_at={member.remote: 6})
    with pytest.raises((ConnectionError, mod.DatasetVerificationError)):
        mod.download_member(t, member, tmp_path)
    assert not (tmp_path / "auth.txt.gz").exists()
    assert (tmp_path / "auth.txt.gz.part").exists()  # retained for resume


# ---------------------------------------------------------------------------
# Task 4 — unpack gzip → validator CSV layout
# ---------------------------------------------------------------------------


def test_unpack_member_produces_validator_csv(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    member = man.members[0]
    src = tmp_path / "auth.txt.gz"
    src.write_bytes(fake_release["auth"]["gz"])  # type: ignore[arg-type]
    mod.unpack_member(src, member, tmp_path)
    out = tmp_path / "auth.csv"
    assert out.read_bytes() == fake_release["auth"]["plain"]


def test_unpack_corrupt_gzip_fails_loudly_no_csv(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    member = man.members[0]
    src = tmp_path / "auth.txt.gz"
    src.write_bytes(b"not a gzip stream at all")
    with pytest.raises(mod.DatasetVerificationError):
        mod.unpack_member(src, member, tmp_path)
    assert not (tmp_path / "auth.csv").exists()


# ---------------------------------------------------------------------------
# Task 5 — end-to-end orchestration + CLI
# ---------------------------------------------------------------------------


def test_fetch_dataset_clean_run(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    t = FakeTransport(_bodies(fake_release))
    mod.fetch_dataset(tmp_path, transport=t, manifest=man)
    for name in ("auth", "proc", "flows", "redteam"):
        assert (tmp_path / f"{name}.csv").read_bytes() == fake_release[name]["plain"]


def test_fetch_dataset_corrupt_member_aborts_before_any_csv(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    # Poison the 'flows' member's expected digest → verification must fail
    # and NO csv may be written (verify-all-before-unpack guarantee).
    members = list(man.members)
    idx = next(i for i, m in enumerate(members) if m.name == "flows")
    members[idx] = replace(members[idx], sha256="0" * 64)
    poisoned = mod.LanlManifest(base_url=man.base_url, members=tuple(members))  # type: ignore[attr-defined]
    t = FakeTransport(_bodies(fake_release))
    with pytest.raises(mod.DatasetVerificationError):
        mod.fetch_dataset(tmp_path, transport=t, manifest=poisoned)
    for name in ("auth", "proc", "flows", "redteam"):
        assert not (tmp_path / f"{name}.csv").exists()


def test_fetch_dataset_idempotent_noop(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    man = _manifest_from(mod, fake_release)
    t1 = FakeTransport(_bodies(fake_release))
    mod.fetch_dataset(tmp_path, transport=t1, manifest=man)
    t2 = FakeTransport(_bodies(fake_release))
    mod.fetch_dataset(tmp_path, transport=t2, manifest=man)
    # Second run must not re-download anything (final files already verified).
    assert t2.get_calls == []


def test_main_success_exit_zero(
    mod: object,
    tmp_path: Path,
    fake_release: dict[str, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    man = _manifest_from(mod, fake_release)
    t = FakeTransport(_bodies(fake_release))
    monkeypatch.setattr(mod, "_default_transport", lambda: t)
    monkeypatch.setattr(mod, "LANL_2015_MANIFEST", man)
    rc = mod.main(["--dest", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "redteam.csv").is_file()


def test_main_failure_exit_nonzero(
    mod: object,
    tmp_path: Path,
    fake_release: dict[str, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    man = _manifest_from(mod, fake_release)
    members = list(man.members)
    members[0] = replace(members[0], sha256="f" * 64)
    poisoned = mod.LanlManifest(base_url=man.base_url, members=tuple(members))  # type: ignore[attr-defined]
    t = FakeTransport(_bodies(fake_release))
    monkeypatch.setattr(mod, "_default_transport", lambda: t)
    monkeypatch.setattr(mod, "LANL_2015_MANIFEST", poisoned)
    rc = mod.main(["--dest", str(tmp_path)])
    assert rc != 0


def test_main_manifest_override_from_json(
    mod: object,
    tmp_path: Path,
    fake_release: dict[str, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    man = _manifest_from(mod, fake_release)
    spec = {
        "base_url": man.base_url,
        "members": [
            {
                "name": m.name,
                "remote": m.remote,
                "csv_name": m.csv_name,
                "size": m.size,
                "sha256": m.sha256,
            }
            for m in man.members
        ],
    }
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps(spec), encoding="utf-8")
    t = FakeTransport(_bodies(fake_release))
    monkeypatch.setattr(mod, "_default_transport", lambda: t)
    rc = mod.main(["--dest", str(tmp_path), "--manifest", str(mf)])
    assert rc == 0
    assert (tmp_path / "auth.csv").is_file()


# ---------------------------------------------------------------------------
# Manifest loading + URL guard + transport + edge paths
# ---------------------------------------------------------------------------


def test_manifest_from_json_round_trip(mod: object, tmp_path: Path) -> None:
    spec = {
        "base_url": "https://x/",
        "members": [
            {
                "name": "auth",
                "remote": "https://x/auth.txt.gz",
                "csv_name": "auth.csv",
                "size": 9,
                "sha256": "a" * 64,
            }
        ],
    }
    p = tmp_path / "m.json"
    p.write_text(json.dumps(spec), encoding="utf-8")
    man = mod.manifest_from_json(p)  # type: ignore[attr-defined]
    assert man.base_url == "https://x/"
    assert man.members[0].name == "auth"
    assert man.members[0].size == 9


def test_manifest_from_json_malformed_fails_loudly(mod: object, tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text('{"base_url": "https://x/"}', encoding="utf-8")  # no "members"
    with pytest.raises(mod.DatasetVerificationError, match="invalid manifest"):
        mod.manifest_from_json(p)  # type: ignore[attr-defined]


def test_member_archive_name_from_remote(mod: object) -> None:
    m = mod.LanlMember(  # type: ignore[attr-defined]
        name="auth",
        remote="https://x/sub/auth.txt.gz",
        csv_name="auth.csv",
        size=1,
        sha256="0" * 64,
    )
    assert m.archive_name == "auth.txt.gz"


def test_check_url_rejects_non_https(mod: object) -> None:
    with pytest.raises(mod.DatasetVerificationError, match="non-https"):
        mod._check_url("http://insecure.example/x")  # type: ignore[attr-defined]
    with pytest.raises(mod.DatasetVerificationError, match="non-https"):
        mod._check_url("file:///etc/passwd")  # type: ignore[attr-defined]
    mod._check_url("https://ok.example/x")  # type: ignore[attr-defined]  # no raise


def test_default_transport_is_urllib(mod: object) -> None:
    assert isinstance(mod._default_transport(), mod.UrllibTransport)  # type: ignore[attr-defined]


class _FakeResp:
    """Context-manager stand-in for ``urllib.request.urlopen``'s return."""

    def __init__(self, headers: dict[str, str], chunks: list[bytes]) -> None:
        self.headers = headers
        self._chunks = list(chunks)

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self, _n: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


def test_urllib_transport_head_parses_headers(
    mod: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(req: object, timeout: int = 0) -> _FakeResp:
        captured["url"] = req.full_url  # type: ignore[attr-defined]
        return _FakeResp({"Content-Length": "42", "Accept-Ranges": "bytes"}, [])

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)  # type: ignore[attr-defined]
    length, accept = mod.UrllibTransport().head("https://ok.example/a.gz")  # type: ignore[attr-defined]
    assert length == 42
    assert accept is True
    assert captured["url"] == "https://ok.example/a.gz"


def test_urllib_transport_get_streams_with_range(
    mod: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_urlopen(req: object, timeout: int = 0) -> _FakeResp:
        seen["range"] = req.get_header("Range")  # type: ignore[attr-defined]
        return _FakeResp({}, [b"abc", b"de"])

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)  # type: ignore[attr-defined]
    out = b"".join(mod.UrllibTransport().get("https://ok.example/a.gz", 3))  # type: ignore[attr-defined]
    assert out == b"abcde"
    assert seen["range"] == "bytes=3-"


def test_urllib_transport_get_from_zero_sends_no_range(
    mod: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_urlopen(req: object, timeout: int = 0) -> _FakeResp:
        seen["range"] = req.get_header("Range")  # type: ignore[attr-defined]
        return _FakeResp({}, [b"xy"])

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)  # type: ignore[attr-defined]
    out = b"".join(mod.UrllibTransport().get("https://ok.example/a.gz", 0))  # type: ignore[attr-defined]
    assert out == b"xy"
    assert seen["range"] is None  # no Range header when starting at 0


def test_urllib_transport_get_rejects_non_https(mod: object) -> None:
    with pytest.raises(mod.DatasetVerificationError):
        list(mod.UrllibTransport().get("http://x/a", 0))  # type: ignore[attr-defined]


def test_download_replaces_stale_final(
    mod: object, tmp_path: Path, fake_release: dict[str, dict[str, object]]
) -> None:
    """A pre-existing but wrong final file is detected and re-downloaded."""
    man = _manifest_from(mod, fake_release)
    member = man.members[0]
    (tmp_path / member.archive_name).write_bytes(b"stale wrong bytes")
    t = FakeTransport(_bodies(fake_release))
    mod.download_member(t, member, tmp_path)
    assert (tmp_path / member.archive_name).read_bytes() == fake_release["auth"]["gz"]


def test_main_io_error_returns_two(
    mod: object,
    tmp_path: Path,
    fake_release: dict[str, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    man = _manifest_from(mod, fake_release)
    t = FakeTransport(_bodies(fake_release))
    monkeypatch.setattr(mod, "_default_transport", lambda: t)
    monkeypatch.setattr(mod, "LANL_2015_MANIFEST", man)

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(mod, "fetch_dataset", boom)
    rc = mod.main(["--dest", str(tmp_path)])
    assert rc == 2
