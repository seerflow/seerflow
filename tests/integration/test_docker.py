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
def built_image() -> None:
    """Build the Docker image once for all tests in this module."""
    result = _docker(["build", "-t", IMAGE_NAME, "."], timeout=600)
    assert result.returncode == 0, f"Docker build failed:\n{result.stderr}"


class TestDockerImage:
    def test_image_size_under_200mb(self) -> None:
        """Compressed image size must be under 200MB."""
        save = subprocess.Popen(  # noqa: S603
            ["docker", "save", IMAGE_NAME],  # noqa: S607
            stdout=subprocess.PIPE,
        )
        gzip_proc = subprocess.Popen(
            ["gzip"],  # noqa: S607
            stdin=save.stdout,
            stdout=subprocess.PIPE,
        )
        assert save.stdout is not None
        save.stdout.close()
        compressed, _ = gzip_proc.communicate(timeout=300)
        compressed_bytes = len(compressed)
        max_bytes = MAX_IMAGE_SIZE_MB * 1024 * 1024
        assert compressed_bytes < max_bytes, (
            f"Compressed image is {compressed_bytes / (1024 * 1024):.0f}MB, "
            f"exceeds {MAX_IMAGE_SIZE_MB}MB limit"
        )

    def test_runs_as_seerflow_user(self) -> None:
        """Container must run as the dedicated non-root 'seerflow' user (uid 10001)."""
        whoami = _docker(["run", "--rm", IMAGE_NAME, "whoami"])
        assert whoami.stdout.strip() == "seerflow"
        uid = _docker(["run", "--rm", IMAGE_NAME, "id", "-u"])
        assert uid.stdout.strip() == "10001"
        gid = _docker(["run", "--rm", IMAGE_NAME, "id", "-g"])
        assert gid.stdout.strip() == "10001"

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
        # /proc/1/cmdline uses NUL bytes as argument separators
        cmdline = result.stdout.replace("\x00", " ").strip()
        assert "tini" in cmdline, f"Expected tini as PID 1, got: {cmdline!r}"

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

    def test_healthcheck_uses_health_endpoint(self) -> None:
        """Healthcheck must probe /api/v1/health via Python urllib (S-080 wiring)."""
        result = _docker(
            [
                "inspect",
                IMAGE_NAME,
                "--format",
                "{{json .Config.Healthcheck}}",
            ]
        )
        healthcheck = result.stdout.strip()
        assert "/api/v1/health" in healthcheck, (
            f"Healthcheck must call /api/v1/health, got: {healthcheck}"
        )
        assert "urllib.request" in healthcheck or "urlopen" in healthcheck, (
            f"Healthcheck must use Python urllib (no apt curl/wget), got: {healthcheck}"
        )

    def test_healthcheck_has_start_period(self) -> None:
        """Healthcheck must declare a non-zero StartPeriod to tolerate warmup."""
        result = _docker(
            [
                "inspect",
                IMAGE_NAME,
                "--format",
                "{{.Config.Healthcheck.StartPeriod}}",
            ]
        )
        start_period = result.stdout.strip()
        # Docker prints durations in nanoseconds; anything > 0 is acceptable.
        assert start_period not in ("0", "0s", ""), (
            f"Healthcheck StartPeriod must be set, got: {start_period!r}"
        )
