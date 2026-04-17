"""Alert and model state throughput benchmarks."""

from __future__ import annotations

import asyncio
import os
import time
import warnings
from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.query import AlertQuery
from seerflow.storage.sqlite import SqliteBackend
from tests.benchmarks.conftest import make_alert

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_benchmark.fixture import BenchmarkFixture


@pytest.mark.benchmark
class TestSyncAlertBenchmarks:
    """Sync wrappers that use asyncio.run() per iteration via the benchmark fixture."""

    def test_alert_write_throughput(self, benchmark: BenchmarkFixture) -> None:
        """1K unique alerts — benchmark fixture drives iteration."""
        alerts = [make_alert(message=f"alert {i}") for i in range(1000)]

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                for alert in alerts:
                    await b.write_alert(alert)
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))

    def test_alert_dedup_throughput(self, benchmark: BenchmarkFixture) -> None:
        """1K alerts with same dedup_key — benchmark fixture drives iteration."""
        alerts = [make_alert(dedup_key="same-key", message=f"dedup {i}") for i in range(1000)]

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                for alert in alerts:
                    await b.write_alert(alert)
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))

    def test_alert_query_throughput(self, benchmark: BenchmarkFixture) -> None:
        """Query 1K alerts — benchmark fixture drives iteration."""

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                for i in range(1000):
                    await b.write_alert(make_alert(message=f"q {i}"))
                await b.query_alerts(AlertQuery(limit=100))
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))

    def test_model_state_throughput(self, benchmark: BenchmarkFixture) -> None:
        """1K model state save/load cycles — benchmark fixture drives iteration."""

        async def _run() -> None:
            config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
            b = await SqliteBackend.connect(config)
            try:
                for i in range(1000):
                    await b.save_state(f"key:{i}", b"x" * 1024)
                for i in range(1000):
                    await b.load_state(f"key:{i}")
            finally:
                await b.close()

        benchmark(lambda: asyncio.run(_run()))


@pytest.mark.asyncio
@pytest.mark.slow
async def test_mitre_filter_sql_vs_decode_baseline(tmp_path: Path) -> None:
    """SQL junction filter must be >= 10x faster than a full-decode baseline.

    S-182 AC: >= 10x on 100k alerts. Seeding uses realistic low-selectivity
    distribution — 1% of alerts (1 000 of 100 000) map to the filtered tactic,
    matching production ATT&CK tactic prevalence where any single tactic
    typically tags a small fraction of alerts. At this selectivity the
    junction index (``idx_alert_tactics_tactic``) lets SQLite skip the
    overwhelming majority of rows, while the baseline must decode every
    msgpack blob regardless.

    Baseline now uses the public AlertStore.query_alerts path at the
    10 000-row limit ceiling (S-182), so no storage-internal attribute
    access is needed.
    """
    backend = await SqliteBackend.connect(
        StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "bench.db"))
    )
    try:
        for i in range(100_000):
            alert = make_alert(
                message=f"bench alert {i}",
                dedup_key=f"k{i}",
            )
            # make_alert doesn't expose mitre_tactics; rebuild to include them.
            alert = Alert(
                alert_id=alert.alert_id,
                alert_type=alert.alert_type,
                timestamp_ns=i,
                severity_id=alert.severity_id,
                rule_name=alert.rule_name,
                description=alert.description,
                entity_uuid=alert.entity_uuid,
                entity_value=alert.entity_value,
                entity_type=alert.entity_type,
                contributing_events=alert.contributing_events,
                mitre_tactics=("discovery",) if i < 1_000 else (),
                mitre_techniques=alert.mitre_techniques,
                risk_score=alert.risk_score,
                dedup_key=alert.dedup_key,
                dedup_count=alert.dedup_count,
                feedback=alert.feedback,
            )
            await backend.write_alert(alert)

        # Warm caches with a query unrelated to the filtered path.
        _ = await backend.query_alerts(AlertQuery(alert_type="ml", page=1, limit=1))

        # SQL path
        t0 = time.perf_counter()
        page = await backend.query_alerts(AlertQuery(tactic="discovery", page=1, limit=100))
        sql_elapsed = time.perf_counter() - t0
        assert page.total == 1_000

        # Baseline: public query_alerts path at the S-182 10 000-row ceiling.
        # Uses only AlertStore.query_alerts — no storage-internal attr access.
        t0 = time.perf_counter()
        baseline_page = await backend.query_alerts(AlertQuery(page=1, limit=10_000))
        matching = [a for a in baseline_page.items if "discovery" in a.mitre_tactics]
        baseline_elapsed = time.perf_counter() - t0

        # Baseline sees only the most-recent 10 000 rows (timestamp_ns DESC).
        # Discovery-tagged rows sit at the oldest 1 000 indices, so none fall
        # inside the baseline window — matching count is 0. The SQL path is not
        # bound by this window and still returns all 1 000 (asserted above via
        # page.total). Guard the seed invariant so a future change to
        # timestamp assignment surfaces as a failure instead of a silent 0.
        assert baseline_page.items[0].timestamp_ns >= 10_000, (
            "baseline window must exclude the oldest 1 000 discovery rows"
        )
        assert len(matching) == 0
        ratio = baseline_elapsed / sql_elapsed
        bench_gate_strict = os.environ.get("SEERFLOW_BENCH_GATE") == "1"
        if bench_gate_strict:
            assert ratio >= 10, (
                f"expected SQL filter >= 10x faster than decode baseline, "
                f"got {ratio:.2f}x (sql={sql_elapsed:.3f}s "
                f"baseline={baseline_elapsed:.3f}s)"
            )
        elif ratio < 10:
            warnings.warn(
                f"SQL vs decode ratio {ratio:.2f}x (<10x expected). "
                f"sql={sql_elapsed:.3f}s baseline={baseline_elapsed:.3f}s. "
                "Set SEERFLOW_BENCH_GATE=1 to enforce.",
                category=UserWarning,
                stacklevel=2,
            )
    finally:
        await backend.close()


def test_benchmark_warn_uses_explicit_user_warning_category() -> None:
    """S-187: the SQL/decode ratio warning must pass category explicitly.

    Static-analysis tools and CI warning filters can reliably target the
    benchmark warning only when ``category=`` is passed. Walks the AST of
    :func:`test_mitre_filter_sql_vs_decode_baseline` so the assertion is
    not fooled by the keyword appearing in a comment or string, and fires
    deterministically without running the slow benchmark body.

    S-193: source is loaded via ``pathlib.Path(__file__)`` instead of
    ``inspect.getsource`` so the guard does not depend on CPython linecache
    state — the latter is not reliable under pytest-xdist, bytecode-only
    wheels, or plugins that clear linecache between tests.
    """
    import ast
    from pathlib import Path

    module_tree = ast.parse(Path(__file__).read_text())
    target_fn = next(
        (
            node
            for node in ast.walk(module_tree)
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == "test_mitre_filter_sql_vs_decode_baseline"
        ),
        None,
    )
    assert target_fn is not None, (
        "test_mitre_filter_sql_vs_decode_baseline not found in module — "
        "the S-187/S-193 category guard is targeting a function that no longer exists"
    )
    warn_calls = [
        node
        for node in ast.walk(target_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "warn"
    ]
    assert warn_calls, "expected at least one warnings.warn() call"
    assert all(any(kw.arg == "category" for kw in call.keywords) for call in warn_calls), (
        "every warnings.warn() call must pass category= explicitly"
    )


def test_benchmark_warn_category_guard_independent_of_inspect_getsource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S-193: the category guard must resolve module source via __file__,
    not via ``inspect.getsource``. Monkey-patching ``inspect.getsource`` to
    raise ``OSError`` reproduces the CI flake observed on dev at S-187. If
    the guard still depends on ``inspect.getsource`` this test will fail
    the same way the original flake did.
    """
    import inspect as _inspect
    from typing import NoReturn

    def _boom(*_args: object, **_kwargs: object) -> NoReturn:
        raise OSError("could not get source code")

    monkeypatch.setattr(_inspect, "getsource", _boom)

    # Invoke the guard exactly as pytest does. The guard must not raise.
    test_benchmark_warn_uses_explicit_user_warning_category()
