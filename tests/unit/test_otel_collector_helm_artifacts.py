"""Structural tests for the OTel gateway Helm chart artifacts (S-368).

These tests parse the Helm chart under ``examples/otel-collector/helm/`` and
assert invariants without running ``helm``. They guard FR-007 (gateway
deployment artifacts) and keep the chart in lockstep with the S-367 reference
config and compose path:

* ``Chart.yaml`` and ``values.yaml`` parse as YAML;
* the chart pins ``otel/opentelemetry-collector-contrib`` to the documented
  ``0.147.0`` baseline (never ``:latest``);
* the chart's Seerflow OTLP endpoint targets Seerflow's gRPC receiver port,
  kept in lockstep with ``ReceiverConfig.otlp_grpc_port`` (single source of
  truth — no hardcoded expected port in the assertion);
* the chart reuses the canonical reference Collector config byte-for-byte (one
  source of truth across compose + Helm);
* the templates declare a logs-only Collector (Seerflow ingests the OTLP Logs
  signal only) and never inline cloud credentials;
* the README documents the Helm deployment path and the enriched operator-guide
  cross-link (FR-006 caveats + v0.147.0 pin).

Mirrors ``tests/unit/test_otel_collector_artifacts.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from seerflow.config import ReceiverConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_DIR = REPO_ROOT / "examples" / "otel-collector"
CANONICAL_CONFIG = EXAMPLE_DIR / "otel-collector-config.yaml"
README = EXAMPLE_DIR / "README.md"

HELM_DIR = EXAMPLE_DIR / "helm"
CHART_YAML = HELM_DIR / "Chart.yaml"
VALUES_YAML = HELM_DIR / "values.yaml"
CHART_CONFIG = HELM_DIR / "otel-collector-config.yaml"
TEMPLATES_DIR = HELM_DIR / "templates"
CONFIGMAP_TMPL = TEMPLATES_DIR / "configmap.yaml"
DEPLOYMENT_TMPL = TEMPLATES_DIR / "deployment.yaml"
SERVICE_TMPL = TEMPLATES_DIR / "service.yaml"

CONTRIB_IMAGE = "otel/opentelemetry-collector-contrib"
BASELINE_TAG = "0.147.0"


def _endpoint_port(endpoint: str) -> int:
    """Extract the trailing ``:<port>`` from an endpoint string.

    Tolerates env-var defaulting / scheme prefixes by reading the last
    colon-delimited run of digits (matches the helper in
    ``test_otel_collector_artifacts.py``).
    """
    matches = re.findall(r":(\d+)", endpoint)
    if not matches:
        msg = f"no port found in endpoint {endpoint!r}"
        raise AssertionError(msg)
    return int(matches[-1])


@pytest.fixture(scope="module")
def chart_meta() -> dict:
    return yaml.safe_load(CHART_YAML.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def values() -> dict:
    return yaml.safe_load(VALUES_YAML.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def readme_text() -> str:
    return README.read_text(encoding="utf-8")


class TestChartLayout:
    def test_helm_dir_exists(self) -> None:
        assert HELM_DIR.is_dir(), f"missing helm chart dir: {HELM_DIR}"

    def test_required_chart_files_exist(self) -> None:
        for path in (
            CHART_YAML,
            VALUES_YAML,
            CHART_CONFIG,
            CONFIGMAP_TMPL,
            DEPLOYMENT_TMPL,
            SERVICE_TMPL,
        ):
            assert path.is_file(), f"missing chart artifact: {path}"


class TestChartMetadata:
    def test_chart_yaml_parses(self, chart_meta: dict) -> None:
        assert isinstance(chart_meta, dict)

    def test_chart_is_v2_with_name_and_version(self, chart_meta: dict) -> None:
        assert chart_meta.get("apiVersion") == "v2"
        assert chart_meta.get("name"), "Chart.yaml must declare a name"
        assert chart_meta.get("version"), "Chart.yaml must declare a version"

    def test_app_version_matches_baseline(self, chart_meta: dict) -> None:
        # appVersion tracks the deployed Collector contrib release.
        assert str(chart_meta.get("appVersion")) == BASELINE_TAG


class TestChartValues:
    def test_values_yaml_parses(self, values: dict) -> None:
        assert isinstance(values, dict)

    def test_image_repository_is_contrib(self, values: dict) -> None:
        assert values["image"]["repository"] == CONTRIB_IMAGE

    def test_image_tag_pins_documented_baseline(self, values: dict) -> None:
        tag = str(values["image"]["tag"])
        assert tag == BASELINE_TAG, f"image.tag must pin {BASELINE_TAG}; got {tag!r}"

    def test_image_tag_not_latest(self, values: dict) -> None:
        assert str(values["image"]["tag"]) != "latest"

    def test_seerflow_otlp_endpoint_targets_grpc_port(self, values: dict) -> None:
        endpoint = values["seerflow"]["otlpEndpoint"]
        assert endpoint, "values must declare seerflow.otlpEndpoint"
        # Single source of truth: must match Seerflow's actual gRPC receiver port.
        assert _endpoint_port(endpoint) == ReceiverConfig().otlp_grpc_port

    def test_no_inline_cloud_credentials(self, values: dict) -> None:
        # Credentials come from an existing K8s Secret referenced by name; the
        # chart must never inline secret material.
        text = VALUES_YAML.read_text(encoding="utf-8")
        for forbidden in ("AKIA", "SECRET_ACCESS_KEY:", "connection_string:"):
            assert forbidden not in text, f"values must not inline {forbidden!r}"
        assert "secretRef" in values, "values must reference a credential Secret by name"


class TestReferenceConfigReuse:
    def test_chart_config_matches_canonical_byte_for_byte(self) -> None:
        # One source of truth: the chart-root config must be identical to the
        # canonical reference config that the compose path also uses.
        assert CHART_CONFIG.read_bytes() == CANONICAL_CONFIG.read_bytes(), (
            "helm chart config drifted from the canonical otel-collector-config.yaml"
        )

    def test_configmap_renders_reference_config(self) -> None:
        text = CONFIGMAP_TMPL.read_text(encoding="utf-8")
        assert "otel-collector-config.yaml" in text, (
            "ConfigMap template must source the reference config filename"
        )


class TestDeploymentTemplate:
    def test_deployment_pins_image_from_values(self) -> None:
        text = DEPLOYMENT_TMPL.read_text(encoding="utf-8")
        assert ".Values.image.repository" in text
        assert ".Values.image.tag" in text

    def test_deployment_mounts_config(self) -> None:
        text = DEPLOYMENT_TMPL.read_text(encoding="utf-8")
        # Collector reads its config from the standard contrib path.
        assert "/etc/otelcol-contrib/config.yaml" in text

    def test_deployment_injects_credentials_from_secret(self) -> None:
        text = DEPLOYMENT_TMPL.read_text(encoding="utf-8")
        assert "secretRef" in text, "deployment must source credentials from the values secretRef"


class TestHelmReadmeDocumentation:
    def test_documents_helm_install(self, readme_text: str) -> None:
        assert "helm install" in readme_text, "README must document the helm install path"

    def test_documents_helm_section(self, readme_text: str) -> None:
        assert re.search(r"#+\s+Kubernetes \(Helm\)", readme_text), (
            "README must include a 'Kubernetes (Helm)' section"
        )

    def test_documents_version_pin_in_chart(self) -> None:
        # The v0.147.0 baseline must be discoverable in the chart itself.
        assert BASELINE_TAG in VALUES_YAML.read_text(encoding="utf-8")

    def test_crosslink_names_caveats_and_pin(self, readme_text: str) -> None:
        # AC3: the operator-guide cross-link must, *in the cross-link region
        # itself*, name the FR-006 caveats and the contrib version pin.
        assert "operator-guide.md" in readme_text, "README must cross-link the operator guide"
        # The "See also" bullet that carries the operator-guide pointer. Slice
        # from the operator-guide mention to the next top-level bullet so the
        # keyword checks are scoped to the enriched cross-link, not the whole file.
        start = readme_text.index("operator-guide.md")
        next_bullet = readme_text.find("\n- ", start)
        link_region = readme_text[start : next_bullet if next_bullet != -1 else len(readme_text)]
        for keyword in (BASELINE_TAG, "caveat"):
            assert keyword in link_region, (
                f"operator-guide cross-link must name {keyword!r} (FR-006 caveats / version pin)"
            )
