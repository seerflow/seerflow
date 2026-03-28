"""Integration tests for the Docker image.

These tests build and run the Docker image to verify acceptance criteria.
Requires Docker to be running. Skip with: pytest -m "not docker"
"""

from __future__ import annotations

import subprocess

import pytest

pytestmark = pytest.mark.docker

IMAGE_NAME = "seerflow:test"
MAX_IMAGE_SIZE_MB = 200


def _docker(
    args: list[str], *, check: bool = True, timeout: int = 300
) -> subprocess.CompletedProcess[str]:
    """Run a docker command and return the result."""
    return subprocess.run(  # noqa: S603
        ["docker", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


@pytest.fixture(scope="module", autouse=True)
def built_image() -> str:
    """Build the Docker image once for all tests in this module."""
    result = _docker(["build", "-t", IMAGE_NAME, "."], timeout=600)
    assert result.returncode == 0, f"Docker build failed:\n{result.stderr}"
    return IMAGE_NAME


class TestDockerImage:
    def test_image_size_under_200mb(self) -> None:
        """Compressed image size must be under 200MB."""
        result = subprocess.run(  # noqa: S603
            ["bash", "-c", f"docker save {IMAGE_NAME} | gzip | wc -c"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=300,
        )
        compressed_bytes = int(result.stdout.strip())
        max_bytes = MAX_IMAGE_SIZE_MB * 1024 * 1024
        assert compressed_bytes < max_bytes, (
            f"Compressed image is {compressed_bytes / (1024 * 1024):.0f}MB, "
            f"exceeds {MAX_IMAGE_SIZE_MB}MB limit"
        )

    def test_runs_as_non_root(self) -> None:
        """Container must run as non-root user 'nobody'."""
        result = _docker(["run", "--rm", IMAGE_NAME, "whoami"])
        assert result.stdout.strip() == "nobody"

    def test_version_command(self) -> None:
        """'seerflow --version' must work inside the container."""
        result = _docker(["run", "--rm", IMAGE_NAME, "seerflow", "--version"])
        assert "seerflow" in result.stdout.strip()

    def test_uv_not_in_runtime(self) -> None:
        """uv must not be present in the runtime image."""
        result = _docker(["run", "--rm", IMAGE_NAME, "which", "uv"], check=False)
        assert result.returncode != 0, "uv should not be in the runtime image"

    def test_tini_is_pid_1(self) -> None:
        """tini must be the init process (PID 1)."""
        result = _docker(["run", "--rm", IMAGE_NAME, "cat", "/proc/1/cmdline"])
        assert "tini" in result.stdout

    def test_ports_exposed(self) -> None:
        """Image must expose 8080/tcp, 4317/tcp, 4318/tcp, 514/udp."""
        result = _docker(
            [
                "inspect",
                IMAGE_NAME,
                "--format",
                "{{json .Config.ExposedPorts}}",
            ]
        )
        exposed = result.stdout.strip()
        assert "8080/tcp" in exposed
        assert "4317/tcp" in exposed
        assert "4318/tcp" in exposed
        assert "514/udp" in exposed

    def test_healthcheck_configured(self) -> None:
        """Healthcheck must reference 'seerflow' and '--version'."""
        result = _docker(
            [
                "inspect",
                IMAGE_NAME,
                "--format",
                "{{json .Config.Healthcheck}}",
            ]
        )
        healthcheck = result.stdout.strip()
        assert "seerflow" in healthcheck
        assert "--version" in healthcheck
