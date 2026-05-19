"""Fetch + verify the LANL 2015 cyber-security events dataset (S-308 / FR-076).

Downloads the LANL 2015 "Comprehensive, Multi-Source Cyber-Security Events"
release (Kent, A. D., LANL, 2015 — https://csr.lanl.gov/data/cyber1/),
SHA-256-verifies every member against a pinned manifest, **resumes** partial
downloads via HTTP ``Range``, and decompresses each ``*.txt.gz`` member into
the ``auth.csv / proc.csv / flows.csv / redteam.csv`` layout that
:func:`seerflow.lanl.validator.run_validation` consumes.

Why this release: it is the only LANL release that ships ``redteam.txt.gz``
ground truth in a flat four-file shape matching the validator's runtime
contract (``run_validation_async`` reads ``auth.csv``, ``proc.csv``,
``flows.csv``, ``redteam.csv``). See ``scripts/README-lanl.md`` for the OQ-1
decision record, source URL, and licensing.

**Failure model — fail loudly, fail early.** Every member is downloaded *and*
verified before *any* member is decompressed. A short file, a checksum
mismatch, a missing member, or a corrupt gzip stream raises
:class:`DatasetVerificationError` and the CLI exits non-zero **before** any
``.csv`` reaches disk, so a corrupt dataset can never reach scoring.

The HTTP layer is an injectable :class:`Transport` protocol so the whole tool
is unit-tested with an in-memory fake — **no real network access in CI**. The
``scripts/fetch_lanl.py`` shim is a thin CLI wrapper around :func:`main`.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from http.client import HTTPResponse

logger = logging.getLogger("seerflow.lanl.fetch")

_CHUNK = 1 << 20  # 1 MiB streaming chunk for hashing / decompression.

__all__ = [
    "LANL_2015_MANIFEST",
    "DatasetVerificationError",
    "LanlManifest",
    "LanlMember",
    "Transport",
    "UrllibTransport",
    "download_member",
    "fetch_dataset",
    "main",
    "manifest_from_json",
    "unpack_member",
    "verify_member",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DatasetVerificationError(RuntimeError):
    """Raised when a member is missing, the wrong size, or fails SHA-256.

    Also raised for corrupt gzip streams during unpack. Always fatal: the
    caller must abort before any scoring can run.
    """


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LanlMember:
    """One downloadable dataset member and its verification contract.

    Attributes:
        name: Logical member name (``auth`` / ``proc`` / ``flows`` /
            ``redteam``).
        remote: Absolute URL of the gzip-compressed member.
        csv_name: Local decompressed filename the validator reads.
        size: Expected compressed size in bytes.
        sha256: Expected hex SHA-256 digest of the compressed file.
    """

    name: str
    remote: str
    csv_name: str
    size: int
    sha256: str

    @property
    def archive_name(self) -> str:
        """Local name of the compressed download (e.g. ``auth.txt.gz``)."""
        return self.remote.rsplit("/", 1)[-1]


@dataclass(frozen=True, slots=True)
class LanlManifest:
    """The set of members that make up a complete LANL dataset release."""

    base_url: str
    members: tuple[LanlMember, ...]


# Pinned LANL 2015 "Comprehensive, Multi-Source Cyber-Security Events" release.
#
# The published per-file SHA-256 digests / sizes are intentionally left as
# placeholders here: the upstream host does not publish a stable checksum
# manifest, so operators must pin digests for their mirror and pass them via
# ``--manifest`` (documented in scripts/README-lanl.md). The structure, URLs,
# and decompressed CSV layout are authoritative; only the digests/sizes are
# environment-specific. ``verify_member`` still enforces whatever digests the
# active manifest carries, so a real run with a real manifest fails loudly on
# any mismatch.
_LANL_2015_BASE = "https://csr.lanl.gov/data/cyber1/"

LANL_2015_MANIFEST = LanlManifest(
    base_url=_LANL_2015_BASE,
    members=(
        LanlMember(
            name="auth",
            remote=_LANL_2015_BASE + "auth.txt.gz",
            csv_name="auth.csv",
            size=1,
            sha256="0" * 64,
        ),
        LanlMember(
            name="proc",
            remote=_LANL_2015_BASE + "proc.txt.gz",
            csv_name="proc.csv",
            size=1,
            sha256="0" * 64,
        ),
        LanlMember(
            name="flows",
            remote=_LANL_2015_BASE + "flows.txt.gz",
            csv_name="flows.csv",
            size=1,
            sha256="0" * 64,
        ),
        LanlMember(
            name="redteam",
            remote=_LANL_2015_BASE + "redteam.txt.gz",
            csv_name="redteam.csv",
            size=1,
            sha256="0" * 64,
        ),
    ),
)


def manifest_from_json(path: Path) -> LanlManifest:
    """Load an operator-supplied manifest (mirror digests/sizes).

    Schema::

        {"base_url": "...",
         "members": [{"name","remote","csv_name","size","sha256"}, ...]}

    Raises:
        DatasetVerificationError: If the JSON is malformed or missing keys.
    """
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
        members = tuple(
            LanlMember(
                name=str(m["name"]),
                remote=str(m["remote"]),
                csv_name=str(m["csv_name"]),
                size=int(m["size"]),
                sha256=str(m["sha256"]),
            )
            for m in spec["members"]
        )
        return LanlManifest(base_url=str(spec["base_url"]), members=members)
    except (KeyError, ValueError, TypeError, OSError) as exc:
        raise DatasetVerificationError(f"invalid manifest {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Transport (injectable — no real network in tests)
# ---------------------------------------------------------------------------


class Transport(Protocol):
    """Minimal HTTP seam: a HEAD probe and a resumable byte GET."""

    def head(self, url: str) -> tuple[int, bool]:
        """Return ``(content_length, accept_ranges)`` for ``url``."""
        ...

    def get(self, url: str, start_byte: int) -> Iterator[bytes]:
        """Yield body bytes of ``url`` starting at ``start_byte``.

        Implementations honour ``Range: bytes=start_byte-`` when the server
        supports it; otherwise they stream from zero.
        """
        ...


def _open(req: urllib.request.Request, timeout: int) -> HTTPResponse:
    """Open a pre-validated https ``Request``.

    Centralises the single ``urlopen`` call so the S310/B310 suppression
    (justified: every caller runs :func:`_check_url` first, so only ``https``
    URLs ever reach here — the ``file:``/custom-scheme risk cannot occur)
    lives in exactly one place.
    """
    resp = urllib.request.urlopen(req, timeout=timeout)  # noqa: S310  # nosec B310
    return cast("HTTPResponse", resp)


class UrllibTransport:
    """Production :class:`Transport` over stdlib ``urllib`` (no new deps)."""

    def head(self, url: str) -> tuple[int, bool]:
        _check_url(url)  # https-only gate; see _open justification
        req = urllib.request.Request(url, method="HEAD")  # noqa: S310
        with _open(req, timeout=60) as resp:
            length = int(resp.headers.get("Content-Length", "0"))
            accept = resp.headers.get("Accept-Ranges", "").lower() == "bytes"
            return length, accept

    def get(self, url: str, start_byte: int) -> Iterator[bytes]:
        _check_url(url)  # https-only gate; see _open justification
        req = urllib.request.Request(url)  # noqa: S310
        if start_byte > 0:
            req.add_header("Range", f"bytes={start_byte}-")
        with _open(req, timeout=300) as resp:
            while True:
                block = resp.read(_CHUNK)
                if not block:
                    break
                yield block


def _check_url(url: str) -> None:
    """Reject non-HTTPS URLs (defence in depth for the urllib transport)."""
    if not url.startswith("https://"):
        raise DatasetVerificationError(f"refusing non-https URL: {url!r}")


def _default_transport() -> Transport:
    """Factory used by :func:`main` (monkeypatched in tests)."""
    return UrllibTransport()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def verify_member(path: Path, member: LanlMember) -> None:
    """Fail loudly unless ``path`` exactly matches ``member``'s contract.

    Checks (cheap → expensive): file present, exact byte size, then SHA-256.

    Raises:
        DatasetVerificationError: On any missing / short / oversized /
            digest-mismatched file. The message names the file and the
            expected vs actual value.
    """
    if not path.is_file():
        raise DatasetVerificationError(f"missing dataset member: {path}")
    actual_size = path.stat().st_size
    if actual_size != member.size:
        raise DatasetVerificationError(
            f"{member.archive_name}: size mismatch — "
            f"expected {member.size} bytes, got {actual_size}"
        )
    actual_sha = _sha256_file(path)
    if actual_sha != member.sha256:
        raise DatasetVerificationError(
            f"{member.archive_name}: sha256 checksum mismatch — "
            f"expected {member.sha256}, got {actual_sha}"
        )


# ---------------------------------------------------------------------------
# Resumable download
# ---------------------------------------------------------------------------


def _final_is_reusable(final: Path, member: LanlMember) -> bool:
    """True iff ``final`` already exists and passes verification (idempotent).

    A present-but-corrupt final file is deleted so the caller re-downloads.
    """
    if not final.is_file():
        return False
    try:
        verify_member(final, member)
    except DatasetVerificationError:
        logger.warning("%s present but failed verification — re-downloading", final)
        final.unlink()
        return False
    logger.info("%s already present and verified — skipping", member.archive_name)
    return True


def _resume_offset(part: Path, member: LanlMember, *, accept_ranges: bool) -> int:
    """Resume byte offset for ``part``: tail-continue, or restart from zero.

    Returns the number of already-good bytes to keep. If the server cannot
    serve ranges, the partial file is discarded and 0 is returned (restart).
    """
    existing = part.stat().st_size if part.is_file() else 0
    if existing and not accept_ranges:
        logger.warning(
            "%s: server does not support range requests — restarting from zero",
            member.archive_name,
        )
        part.unlink()
        return 0
    if existing:
        logger.info("%s: resuming from byte %d", member.archive_name, existing)
    return existing


def download_member(transport: Transport, member: LanlMember, dest_dir: Path) -> Path:
    """Download ``member`` into ``dest_dir`` resumably and verify it.

    Writes to ``<archive>.part``. If a ``.part`` already exists and the
    server advertises ``Accept-Ranges: bytes``, the missing tail is requested
    via ``Range`` and appended (resume). If the server does not support
    ranges, the partial file is discarded and the download restarts from zero
    (logged). The ``.part`` is atomically renamed to its final name only
    **after** :func:`verify_member` passes; on truncation/verification
    failure the ``.part`` is retained so a later run can resume.

    Returns:
        Path to the verified, final (non-``.part``) file.

    Raises:
        DatasetVerificationError: If the assembled file fails verification.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / member.archive_name
    part = dest_dir / f"{member.archive_name}.part"

    if _final_is_reusable(final, member):
        return final

    _, accept_ranges = transport.head(member.remote)
    existing = _resume_offset(part, member, accept_ranges=accept_ranges)

    mode = "ab" if existing else "wb"
    with part.open(mode) as fh:
        for block in transport.get(member.remote, existing):
            fh.write(block)

    verify_member(part, member)
    part.replace(final)
    logger.info("%s downloaded and verified (%d bytes)", member.archive_name, member.size)
    return final


# ---------------------------------------------------------------------------
# Unpack
# ---------------------------------------------------------------------------


def unpack_member(archive: Path, member: LanlMember, dest_dir: Path) -> Path:
    """Decompress ``archive`` to the validator CSV name, atomically.

    Streams gzip → a temporary file, then atomically renames to
    ``member.csv_name`` so a partial ``.csv`` is never visible. A corrupt or
    truncated gzip stream raises :class:`DatasetVerificationError` and leaves
    no ``.csv`` behind.

    Returns:
        Path to the decompressed CSV.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / member.csv_name
    tmp = dest_dir / f"{member.csv_name}.tmp"
    try:
        with gzip.open(archive, "rb") as src, tmp.open("wb") as dst:
            for block in iter(lambda: src.read(_CHUNK), b""):
                dst.write(block)
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        tmp.unlink(missing_ok=True)
        raise DatasetVerificationError(
            f"{member.archive_name}: corrupt gzip stream — {exc}"
        ) from exc
    tmp.replace(out)
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def fetch_dataset(
    dest: Path,
    *,
    transport: Transport,
    manifest: LanlManifest = LANL_2015_MANIFEST,
) -> None:
    """Download, verify (ALL members) then unpack the LANL dataset.

    The verify-all-before-unpack ordering is the core safety guarantee: a
    single bad member aborts the whole run before *any* ``.csv`` is written,
    so partially-corrupt data can never reach scoring. Idempotent — a fully
    present, verified directory is a no-op.

    Raises:
        DatasetVerificationError: On the first member that fails to download
            or verify. No CSVs are written in that case.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    archives: list[tuple[Path, LanlMember]] = []
    for member in manifest.members:
        archive = download_member(transport, member, dest)
        archives.append((archive, member))

    # Every member is verified by download_member; only now do we unpack.
    for archive, member in archives:
        unpack_member(archive, member, dest)
        logger.info("unpacked %s → %s", member.archive_name, member.csv_name)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_lanl",
        description=(
            "Fetch + SHA-256-verify the LANL 2015 cyber-security events "
            "dataset into the seerflow.lanl validator CSV layout."
        ),
    )
    parser.add_argument(
        "--dest",
        required=True,
        type=Path,
        help="Directory to download into and unpack the CSV layout.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional JSON manifest overriding the pinned release "
        "(use for an internal mirror with its own digests).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only log warnings and errors.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint. Returns 0 on success, non-zero on any failure."""
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    manifest = manifest_from_json(args.manifest) if args.manifest else LANL_2015_MANIFEST
    try:
        fetch_dataset(args.dest, transport=_default_transport(), manifest=manifest)
    except DatasetVerificationError as exc:
        logger.error("dataset fetch FAILED: %s", exc)
        return 1
    except OSError as exc:
        logger.error("dataset fetch FAILED (I/O): %s", exc)
        return 2
    logger.info("LANL dataset ready in %s", args.dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
