"""Integration test for ``seerflow status`` (S-075).

Builds the in-process FastAPI app via ``create_api_app``, wires a real
metrics provider whose ensemble exposes a known ``total_model_count``,
then invokes ``run_status`` against the live app using ``httpx`` with an
ASGI transport. No port binding required.

The test asserts that:

1. The ``status`` exit code is ``0`` (healthy).
2. The human output prints the precise ``model_count`` derived from the
   ensemble (not the historical ``source_count * _DETECTORS_PER_SOURCE``
   multiplier).
3. The ``--json`` variant emits a parseable document with the same value.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import TYPE_CHECKING

import httpx
import pytest

from seerflow.api.app import create_api_app
from seerflow.api.metrics import build_pipeline_metrics_provider
from seerflow.config import StorageConfig
from seerflow.status_cmd import EXIT_HEALTHY, run_status
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


# Heterogeneous ensemble: 2 sources with non-uniform detector counts (3 + 4 = 7).
# A uniform `_DETECTORS_PER_SOURCE = 4` fallback would render 8 — the precise
# value confirms the metrics provider read `total_model_count` from the ensemble.
_EXPECTED_MODEL_COUNT = 7


class _StubEnsemble:
    """Lightweight ensemble stand-in exposing ``get_stats`` + ``get_health``.

    Reports a heterogeneous ``total_model_count`` (3 + 4 = 7) so that the
    `seerflow status` model count derives from the ensemble, not from the
    `_DETECTORS_PER_SOURCE = 4` fallback (which would yield 8 for 2 sources).
    """

    def get_stats(self) -> dict[str, int]:
        return {
            "source_count": 2,
            "max_sources": 256,
            "eviction_count": 0,
            "template_hw_count": 0,
            "entity_hw_count": 0,
            "total_model_count": _EXPECTED_MODEL_COUNT,
        }

    def get_health(self) -> dict[str, object]:
        return {"source_count": 2, "total_model_count": _EXPECTED_MODEL_COUNT}


class _StubHandler:
    def get_stats(self) -> tuple[int, int, dict[str, object], float]:
        # (events, anomalies, template_meta, start_time)
        return 100, 0, {}, time.monotonic()


@pytest.fixture
async def backend(tmp_path: Path) -> AsyncIterator[SqliteBackend]:
    """Function-scoped SqliteBackend for the in-process app."""
    config = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "status_integration.db"))
    b = await SqliteBackend.connect(config)
    yield b
    await b.close()


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """Minimal YAML config — host/port not actually dialled, the test patches
    ``_fetch`` to use the in-process ASGI client instead."""
    cfg = tmp_path / "seerflow.yaml"
    cfg.write_text(
        "dashboard_port: 18080\n"
        "health_bind_address: 127.0.0.1\n"
        f"storage:\n  data_dir: {tmp_path}\n",
        encoding="utf-8",
    )
    return cfg


async def _build_app_client(backend: SqliteBackend) -> httpx.AsyncClient:
    """Wire the FastAPI app + metrics provider, return an ASGI httpx client."""
    ensemble = _StubEnsemble()
    handler = _StubHandler()
    app = create_api_app(
        log_store=backend,
        alert_store=backend,
        ensemble=ensemble,
    )
    app.state.pipeline_metrics_provider = build_pipeline_metrics_provider(
        handler=handler,
        ensemble=ensemble,
        started_monotonic=time.monotonic() - 60.0,
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


class TestStatusCommandIntegration:
    """End-to-end: run_status hits the in-process FastAPI app."""

    @pytest.mark.asyncio
    async def test_human_output_reports_ensemble_derived_model_count(
        self,
        backend: SqliteBackend,
        config_file: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = await _build_app_client(backend)
        try:

            async def fake_fetch(
                host: str, port: int, timeout: float
            ) -> tuple[dict[str, object], dict[str, object]]:
                health = (await client.get("/api/v1/health")).json()
                stats = (await client.get("/api/v1/stats")).json()
                return health, stats

            monkeypatch.setattr("seerflow.status_cmd._fetch", fake_fetch)

            args = argparse.Namespace(config=str(config_file), json=False, timeout=3.0)
            code = await run_status(args)
            out = capsys.readouterr().out

            assert code == EXIT_HEALTHY
            assert "Status: healthy" in out
            # Critical assertion: the displayed model_count is the
            # ensemble-derived value (7), NOT 2*4=8 from the fallback.
            assert "model_count" in out
            assert str(_EXPECTED_MODEL_COUNT) in out
            # And the fallback would have rendered 8 — confirm it does NOT.
            for line in out.splitlines():
                if "model_count" in line:
                    assert "8" not in line, (
                        f"model_count line still shows fallback value, got: {line!r}"
                    )
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_json_output_carries_model_count(
        self,
        backend: SqliteBackend,
        config_file: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = await _build_app_client(backend)
        try:

            async def fake_fetch(
                host: str, port: int, timeout: float
            ) -> tuple[dict[str, object], dict[str, object]]:
                health = (await client.get("/api/v1/health")).json()
                stats = (await client.get("/api/v1/stats")).json()
                return health, stats

            monkeypatch.setattr("seerflow.status_cmd._fetch", fake_fetch)

            args = argparse.Namespace(config=str(config_file), json=True, timeout=3.0)
            code = await run_status(args)
            out = capsys.readouterr().out

            assert code == EXIT_HEALTHY
            parsed = json.loads(out)
            assert parsed["status"] == "healthy"
            assert parsed["model_count"] == _EXPECTED_MODEL_COUNT
            assert parsed["active_sources"] == 2
        finally:
            await client.aclose()
