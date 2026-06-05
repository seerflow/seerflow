"""Unit tests for seerflow.lanl.report.hardware (S-358, slice 2).

Tests are entirely synchronous; asyncio_mode=auto is irrelevant here.
Never add @pytest.mark.asyncio.
"""

from __future__ import annotations

import math
from typing import Any

import pytest  # noqa: TC002

from seerflow.lanl.report.schema import HostInfo, Projection

# ---------------------------------------------------------------------------
# _parse_cpuinfo
# ---------------------------------------------------------------------------

CPUINFO_SAMPLE = """\
processor\t: 0
vendor_id\t: GenuineIntel
cpu family\t: 6
model\t\t: 158
model name\t: Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz
stepping\t: 10
physical id\t: 0
cpu cores\t: 6
siblings\t: 12

processor\t: 1
vendor_id\t: GenuineIntel
cpu family\t: 6
model\t\t: 158
model name\t: Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz
stepping\t: 10
physical id\t: 0
cpu cores\t: 6
siblings\t: 12

processor\t: 2
vendor_id\t: GenuineIntel
cpu family\t: 6
model\t\t: 158
model name\t: Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz
stepping\t: 10
physical id\t: 0
cpu cores\t: 6
siblings\t: 12
"""

CPUINFO_TWO_SOCKETS = """\
processor\t: 0
model name\t: Intel(R) Xeon(R) Gold 6154 CPU @ 3.00GHz
physical id\t: 0
cpu cores\t: 18

processor\t: 1
model name\t: Intel(R) Xeon(R) Gold 6154 CPU @ 3.00GHz
physical id\t: 1
cpu cores\t: 18
"""


def test_parse_cpuinfo_model_and_cores() -> None:
    from seerflow.lanl.report.hardware import _parse_cpuinfo

    model, physical = _parse_cpuinfo(CPUINFO_SAMPLE)
    assert model == "Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz"
    assert physical == 6  # one physical id (0) with 6 cores


def test_parse_cpuinfo_two_sockets() -> None:
    from seerflow.lanl.report.hardware import _parse_cpuinfo

    model, physical = _parse_cpuinfo(CPUINFO_TWO_SOCKETS)
    # Two sockets x 18 cores each = 36 physical cores
    assert physical == 36
    assert model is not None and "Xeon" in model


def test_parse_cpuinfo_empty() -> None:
    from seerflow.lanl.report.hardware import _parse_cpuinfo

    model, physical = _parse_cpuinfo("")
    assert model is None
    assert physical is None


MEMINFO_SAMPLE = """\
MemTotal:       16305808 kB
MemFree:         3141224 kB
MemAvailable:    8000000 kB
"""


def test_parse_meminfo_basic() -> None:
    from seerflow.lanl.report.hardware import _parse_meminfo

    ram = _parse_meminfo(MEMINFO_SAMPLE)
    assert ram is not None
    # 16305808 kB / 1024 / 1024 ≈ 15.55 GB
    assert abs(ram - 16305808 / 1024 / 1024) < 0.01


def test_parse_meminfo_missing() -> None:
    from seerflow.lanl.report.hardware import _parse_meminfo

    ram = _parse_meminfo("MemFree: 100 kB\n")
    assert ram is None


def test_parse_meminfo_empty() -> None:
    from seerflow.lanl.report.hardware import _parse_meminfo

    assert _parse_meminfo("") is None


# ---------------------------------------------------------------------------
# detect_host — monkeypatched to raise so fallback paths are exercised
# ---------------------------------------------------------------------------


def test_detect_host_fallback_on_file_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """When /proc/* reads raise, detect_host must return a HostInfo without raising."""
    import seerflow.lanl.report.hardware as hw_mod

    def _raise(*_: Any, **__: Any) -> str:
        raise OSError("simulated read error")

    monkeypatch.setattr(hw_mod, "_read_file", _raise)

    host = hw_mod.detect_host()

    assert isinstance(host, HostInfo)
    assert isinstance(host.platform, str) and host.platform  # non-empty
    # logical_cores may be int (from os.cpu_count) or None; must not raise
    assert host.logical_cores is None or isinstance(host.logical_cores, int)
    # model and physical_cores may be None after fallback
    assert host.cpu_model is None or isinstance(host.cpu_model, str)
    assert host.physical_cores is None or isinstance(host.physical_cores, int)
    # ram_gb may be None
    assert host.ram_gb is None or isinstance(host.ram_gb, float)


def test_detect_host_returns_host_info() -> None:
    """Smoke test: detect_host() returns a HostInfo with a non-empty platform string."""
    from seerflow.lanl.report.hardware import detect_host

    host = detect_host()
    assert isinstance(host, HostInfo)
    assert isinstance(host.platform, str) and len(host.platform) > 0


# ---------------------------------------------------------------------------
# project
# ---------------------------------------------------------------------------

_TOTAL = 1_607_452_967
_EPS = 390.0
_HOST_8 = HostInfo(
    cpu_model="Intel i7",
    physical_cores=4,
    logical_cores=8,
    ram_gb=16.0,
    platform="Linux",
)


def test_project_current_row() -> None:
    from seerflow.lanl.report.hardware import project

    rows = project(_EPS, _TOTAL, _HOST_8)
    current = next(r for r in rows if r.kind == "current")
    expected_eta = _TOTAL / _EPS
    assert current.eta_seconds is not None
    assert abs(current.eta_seconds - expected_eta) < 1.0
    assert f"{_EPS:,.0f}" in current.note


def test_project_parallel_row_for_logical_cores() -> None:
    from seerflow.lanl.report.hardware import project

    rows = project(_EPS, _TOTAL, _HOST_8)
    parallel_rows = [r for r in rows if r.kind == "parallel"]
    # Must include a row for N=8 (logical_cores)
    n8_row = next((r for r in parallel_rows if "8 workers" in r.label), None)
    assert n8_row is not None
    expected = _TOTAL / (_EPS * 8)
    assert n8_row.eta_seconds is not None
    assert abs(n8_row.eta_seconds - expected) < 1.0
    assert "S-356" in n8_row.note


def test_project_parallel_rows_mention_s356() -> None:
    from seerflow.lanl.report.hardware import project

    rows = project(_EPS, _TOTAL, _HOST_8)
    parallel_rows = [r for r in rows if r.kind == "parallel"]
    assert len(parallel_rows) >= 1
    for row in parallel_rows:
        assert "S-356" in row.note


def test_project_target_row_shards() -> None:
    from seerflow.lanl.report.hardware import project

    rows = project(_EPS, _TOTAL, _HOST_8, target_wall_seconds=(86_400,))
    target_rows = [r for r in rows if r.kind == "target"]
    assert len(target_rows) == 1
    expected_shards = math.ceil(_TOTAL / (_EPS * 86_400))
    assert f"{expected_shards:,}" in target_rows[0].note


def test_project_caveat_is_last() -> None:
    from seerflow.lanl.report.hardware import project

    rows = project(_EPS, _TOTAL, _HOST_8)
    assert rows[-1].kind == "caveat"


def test_project_single_core_row_exists() -> None:
    from seerflow.lanl.report.hardware import project

    rows = project(_EPS, _TOTAL, _HOST_8)
    single = next((r for r in rows if r.kind == "single_core"), None)
    assert single is not None
    assert single.eta_seconds is None


def test_project_zero_eps_current_eta_none() -> None:
    from seerflow.lanl.report.hardware import project

    rows = project(0.0, _TOTAL, _HOST_8)
    current = next(r for r in rows if r.kind == "current")
    assert current.eta_seconds is None
    assert "no throughput" in current.note.lower()


def test_project_deduped_parallel_rows() -> None:
    """When logical_cores=1, {1, 2, 4} gives 3 rows — no duplicates."""
    from seerflow.lanl.report.hardware import project

    host_1 = HostInfo(
        cpu_model=None, physical_cores=None, logical_cores=1, ram_gb=None, platform="Linux"
    )
    rows = project(_EPS, _TOTAL, host_1)
    parallel_rows = [r for r in rows if r.kind == "parallel"]
    labels = [r.label for r in parallel_rows]
    assert len(labels) == len(set(labels)), "duplicate parallel labels"


def test_project_none_logical_cores_uses_fallback() -> None:
    """None logical_cores defaults to 1 so projection still runs."""
    from seerflow.lanl.report.hardware import project

    host_none = HostInfo(
        cpu_model=None, physical_cores=None, logical_cores=None, ram_gb=None, platform="Linux"
    )
    rows = project(_EPS, _TOTAL, host_none)
    parallel_rows = [r for r in rows if r.kind == "parallel"]
    # cores=1 → {1, 2, 4}
    assert len(parallel_rows) == 3


def test_project_returns_list_of_projections() -> None:
    from seerflow.lanl.report.hardware import project

    rows = project(_EPS, _TOTAL, _HOST_8)
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, Projection)
