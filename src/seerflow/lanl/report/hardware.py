"""Hardware detection and performance projections for the LANL benchmark report (S-358).

Pure parsing helpers make ``_parse_cpuinfo`` / ``_parse_meminfo`` fully
testable without real ``/proc`` files.  ``detect_host`` reads the files via
the injectable ``_read_file`` helper so tests can monkeypatch it to a raiser.
``project`` is fully pure (no I/O).
"""

from __future__ import annotations

import logging
import math
import os
import platform as _platform
from pathlib import Path

from seerflow.lanl.report.schema import HostInfo, Projection

_log = logging.getLogger("seerflow.lanl.report")

# ---------------------------------------------------------------------------
# Internal file-read helper (monkeypatched in tests)
# ---------------------------------------------------------------------------


def _read_file(path: str) -> str:
    """Return the UTF-8 text content of *path*.

    Raises :class:`OSError` / :class:`FileNotFoundError` on failure — callers
    must handle these explicitly.
    """
    return Path(path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pure parsing helpers
# ---------------------------------------------------------------------------


def _parse_cpuinfo(text: str) -> tuple[str | None, int | None]:
    """Parse ``/proc/cpuinfo`` text and return ``(model_name, physical_cores)``.

    Physical core count is the sum of ``cpu cores`` values across unique
    ``physical id`` sockets.  If the file lacks the relevant fields both
    elements are ``None``.

    Args:
        text: Full text content of ``/proc/cpuinfo``.

    Returns:
        A 2-tuple ``(model_name, physical_cores)``.  Either element may be
        ``None`` if not found in *text*.
    """
    model: str | None = None
    socket_cores: dict[str, int] = {}
    current_physical_id: str | None = None

    for line in text.splitlines():
        if ":" not in line:
            current_physical_id = None
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if key == "model name" and model is None:
            model = value
        elif key == "physical id":
            current_physical_id = value
        elif key == "cpu cores" and current_physical_id is not None:
            try:
                cores = int(value)
            except ValueError:
                pass
            else:
                socket_cores[current_physical_id] = cores

    physical_cores: int | None = sum(socket_cores.values()) if socket_cores else None
    return model, physical_cores


def _parse_meminfo(text: str) -> float | None:
    """Parse ``/proc/meminfo`` text and return RAM in GB.

    Looks for the ``MemTotal`` line, converts the value from kibibytes to
    gigabytes (1 GB = 1 048 576 kB).

    Args:
        text: Full text content of ``/proc/meminfo``.

    Returns:
        RAM in GB as a :class:`float`, or ``None`` if ``MemTotal`` is absent.
    """
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    kb = float(parts[1])
                except ValueError:
                    return None
                return kb / 1024 / 1024
    return None


# ---------------------------------------------------------------------------
# detect_host
# ---------------------------------------------------------------------------


def detect_host() -> HostInfo:
    """Detect hardware/OS metadata from the running system.

    Reads ``/proc/cpuinfo`` and ``/proc/meminfo`` on Linux; falls back
    gracefully to stdlib values on any read failure.  **Never raises.**

    Returns:
        A frozen :class:`~seerflow.lanl.report.schema.HostInfo` instance.
    """
    cpu_model: str | None = None
    physical_cores: int | None = None
    ram_gb: float | None = None

    try:
        cpuinfo_text = _read_file("/proc/cpuinfo")
        cpu_model, physical_cores = _parse_cpuinfo(cpuinfo_text)
    except Exception:
        _log.debug("host detection: /proc/cpuinfo unavailable", exc_info=True)

    if cpu_model is None:
        proc = _platform.processor()
        cpu_model = proc if proc else None

    try:
        meminfo_text = _read_file("/proc/meminfo")
        ram_gb = _parse_meminfo(meminfo_text)
    except Exception:
        _log.debug("host detection: /proc/meminfo unavailable", exc_info=True)

    logical_cores: int | None = os.cpu_count()

    return HostInfo(
        cpu_model=cpu_model,
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        ram_gb=ram_gb,
        platform=_platform.platform(),
    )


# ---------------------------------------------------------------------------
# project
# ---------------------------------------------------------------------------

_DEFAULT_TARGET_WALL_SECONDS: tuple[int, ...] = (86_400,)


def project(
    throughput_eps: float,
    total_events: int,
    host: HostInfo,
    target_wall_seconds: tuple[int, ...] = _DEFAULT_TARGET_WALL_SECONDS,
) -> list[Projection]:
    """Generate a list of performance projections for the benchmark run.

    **Pure function — no I/O.**

    Args:
        throughput_eps:      Measured events-per-second rate from the run.
        total_events:        Total events in the target dataset.
        host:                :class:`~seerflow.lanl.report.schema.HostInfo`
                             from the benchmarked machine.
        target_wall_seconds: One or more wall-clock targets (in seconds) for
                             which to compute the required shard count.

    Returns:
        An ordered :class:`list` of :class:`~seerflow.lanl.report.schema.Projection`
        instances.
    """
    rows: list[Projection] = []

    # 1. Current-rate ETA
    if throughput_eps > 0:
        eta_current: float | None = total_events / throughput_eps
        note_current = f"measured ~{throughput_eps:,.0f} eps"
    else:
        eta_current = None
        note_current = "no throughput — cannot project ETA"

    rows.append(
        Projection(
            kind="current",
            label="full-run ETA at current rate",
            eta_seconds=eta_current,
            note=note_current,
        )
    )

    # 2. Single-core row
    rows.append(
        Projection(
            kind="single_core",
            label="single faster core",
            eta_seconds=None,
            note="scales ~linearly with single-core clock",
        )
    )

    # 3. Parallel rows — deduped ordered set {cores, 2*cores, 4*cores}
    cores = host.logical_cores if host.logical_cores is not None else 1
    seen: set[int] = set()
    parallel_ns: list[int] = []
    for n in (cores, 2 * cores, 4 * cores):
        if n not in seen:
            seen.add(n)
            parallel_ns.append(n)

    for n in parallel_ns:
        eta_parallel: float | None = (
            total_events / (throughput_eps * n) if throughput_eps > 0 else None
        )
        rows.append(
            Projection(
                kind="parallel",
                label=f"if sharded to {n} workers",
                eta_seconds=eta_parallel,
                note="IDEAL/no-overhead — requires sharding NOT yet implemented (S-356)",
            )
        )

    # 4. Target wall-time rows
    for w in target_wall_seconds:
        shards = math.ceil(total_events / (throughput_eps * w)) if throughput_eps > 0 else 0
        rows.append(
            Projection(
                kind="target",
                label=f"finish <= {w / 3600:.0f}h",
                eta_seconds=float(w),
                note=(f"~{shards:,} parallel shards at current per-shard eps (requires S-356)"),
            )
        )

    # 5. Final caveat
    rows.append(
        Projection(
            kind="caveat",
            label="single-threaded today",
            eta_seconds=None,
            note=(
                "more cores give ZERO speedup until S-356 parallelization lands; "
                "every parallel/target row above is conditional on that work"
            ),
        )
    )

    return rows
