"""Structural tests for the OTel Collector gateway reference artifacts (S-367).

These tests parse the reference config, smoke ``docker-compose.yaml`` and
``README.md`` under ``examples/otel-collector/`` and assert invariants without
running a Collector. They guard FR-006 (Cloud Ingestion via OTel Gateway):

* the four cloud receivers are present (``awscloudwatch``,
  ``googlecloudpubsub``, ``azureeventhub``, ``kafka``);
* the ``otlp`` exporter targets Seerflow's gRPC receiver port, kept in lockstep
  with ``ReceiverConfig.otlp_grpc_port`` (single source of truth — no hardcoded
  expected port in the assertion);
* the Collector defines a **logs-only** pipeline (Seerflow ingests the OTLP Logs
  signal only — routing metrics/traces at it would be silently dropped);
* the contrib image tag is pinned to a concrete release (never ``:latest``);
* the README documents the version pin and every required caveat.

Mirrors the artifact-test approach in ``tests/unit/test_docker_artifacts.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from seerflow.config import ReceiverConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_DIR = REPO_ROOT / "examples" / "otel-collector"
COLLECTOR_CONFIG = EXAMPLE_DIR / "otel-collector-config.yaml"
COMPOSE = EXAMPLE_DIR / "docker-compose.yaml"
README = EXAMPLE_DIR / "README.md"

REQUIRED_RECEIVERS = (
    "awscloudwatch",
    "googlecloudpubsub",
    "azureeventhub",
    "kafka",
)


def _endpoint_port(endpoint: str) -> int:
    """Extract the trailing ``:<port>`` from an exporter endpoint string.

    Tolerates env-var defaulting syntax such as
    ``${env:SEERFLOW_OTLP_ENDPOINT:-seerflow:4317}`` by reading the last
    colon-delimited run of digits.
    """
    matches = re.findall(r":(\d+)", endpoint)
    if not matches:
        msg = f"no port found in endpoint {endpoint!r}"
        raise AssertionError(msg)
    return int(matches[-1])


@pytest.fixture(scope="module")
def collector_config() -> dict:
    return yaml.safe_load(COLLECTOR_CONFIG.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def compose_data() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def readme_text() -> str:
    return README.read_text(encoding="utf-8")


class TestArtifactsExist:
    def test_example_dir_exists(self) -> None:
        assert EXAMPLE_DIR.is_dir(), f"missing example dir: {EXAMPLE_DIR}"

    def test_required_files_exist(self) -> None:
        for path in (COLLECTOR_CONFIG, COMPOSE, README):
            assert path.is_file(), f"missing artifact: {path}"


class TestCollectorConfig:
    def test_parses_as_yaml(self, collector_config: dict) -> None:
        assert isinstance(collector_config, dict)

    def test_all_four_cloud_receivers_present(self, collector_config: dict) -> None:
        receivers = collector_config.get("receivers", {})
        receiver_types = {key.split("/", 1)[0] for key in receivers}
        for expected in REQUIRED_RECEIVERS:
            assert expected in receiver_types, (
                f"receiver {expected!r} missing; found {sorted(receiver_types)}"
            )

    def test_otlp_exporter_targets_seerflow_grpc_port(self, collector_config: dict) -> None:
        exporters = collector_config.get("exporters", {})
        otlp = exporters.get("otlp")
        assert otlp is not None, "an 'otlp' exporter must be defined"
        endpoint = otlp.get("endpoint")
        assert endpoint, "otlp exporter must declare an endpoint"
        # Single source of truth: must match Seerflow's actual gRPC receiver port.
        assert _endpoint_port(endpoint) == ReceiverConfig().otlp_grpc_port

    def test_logs_pipeline_wires_all_receivers_to_otlp(self, collector_config: dict) -> None:
        pipelines = collector_config.get("service", {}).get("pipelines", {})
        logs = pipelines.get("logs")
        assert logs is not None, "a 'logs' pipeline must be defined"
        pipeline_receiver_types = {r.split("/", 1)[0] for r in logs.get("receivers", [])}
        for expected in REQUIRED_RECEIVERS:
            assert expected in pipeline_receiver_types, (
                f"logs pipeline missing receiver {expected!r}"
            )
        assert "otlp" in logs.get("exporters", []), "logs pipeline must export via 'otlp'"

    def test_no_nonlog_pipeline_routes_to_seerflow_otlp(self, collector_config: dict) -> None:
        # Seerflow ingests OTLP Logs only; metrics/traces would be silently
        # dropped, so no such pipeline may target the 'otlp' (Seerflow) exporter.
        pipelines = collector_config.get("service", {}).get("pipelines", {})
        for name, pipeline in pipelines.items():
            signal = name.split("/", 1)[0]
            if signal == "logs":
                continue
            assert "otlp" not in pipeline.get("exporters", []), (
                f"non-log pipeline {name!r} must not export to the Seerflow 'otlp' exporter"
            )


class TestComposeArtifact:
    def test_contrib_image_pinned(self, compose_data: dict) -> None:
        services = compose_data.get("services", {})
        images = [svc.get("image", "") for svc in services.values()]
        contrib = [img for img in images if "opentelemetry-collector-contrib" in img]
        assert contrib, f"no contrib collector image found in {images}"
        for img in contrib:
            assert re.search(r":\d+\.\d+\.\d+", img), (
                f"contrib image not pinned to a release: {img}"
            )
            assert not img.endswith(":latest"), f"contrib image uses :latest: {img}"

    def test_pins_documented_baseline_version(self, compose_data: dict) -> None:
        services = compose_data.get("services", {})
        images = [svc.get("image", "") for svc in services.values()]
        contrib = [img for img in images if "opentelemetry-collector-contrib" in img]
        assert any("0.147.0" in img for img in contrib), (
            f"contrib image should pin the documented v0.147.0 baseline; got {contrib}"
        )


class TestReadmeDocumentation:
    def test_documents_version_pin(self, readme_text: str) -> None:
        assert "0.147.0" in readme_text, "README must document the v0.147.0 pin"

    @pytest.mark.parametrize(
        "keyword",
        ["alpha", "beta", "Collibra", "in-memory", "file_storage"],
    )
    def test_documents_required_caveats(self, readme_text: str, keyword: str) -> None:
        assert keyword in readme_text, f"README must document caveat keyword {keyword!r}"

    def test_documents_smoke_path_against_real_receivers(self, readme_text: str) -> None:
        # The end-to-end smoke path must reference Seerflow's real OTLP ports.
        assert "4317" in readme_text or "4318" in readme_text
