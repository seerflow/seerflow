"""Structural unit tests for Docker artifacts (Dockerfile, docker-compose.yml, .dockerignore).

These tests parse the artifacts as text/YAML and assert invariants without needing
a running Docker daemon. They guard the production-hardening requirements set in
S-083 / NFR-011:

* dedicated non-root ``seerflow`` user (uid 10001)
* HEALTHCHECK calling the real ``/api/v1/health`` endpoint (S-080)
* multi-stage slim build with no apt cache leakage
* compose hardened with ``cap_drop``, ``security_opt``, ``read_only``, tmpfs and
  resource limits
* ``.dockerignore`` excludes Python caches and build artifacts

The full size + runtime gate lives in ``tests/integration/test_docker.py`` and is
opt-in via ``pytest -m docker`` (default test run deselects it).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
COMPOSE = REPO_ROOT / "docker-compose.yml"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"


@pytest.fixture(scope="module")
def dockerfile_text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose_data() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dockerignore_lines() -> list[str]:
    return [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


class TestDockerfile:
    def test_two_stages_with_slim_base(self, dockerfile_text: str) -> None:
        from_lines = re.findall(r"^FROM\s+(\S+)", dockerfile_text, flags=re.MULTILINE)
        assert len(from_lines) == 2, f"expected 2 FROM lines, got {from_lines}"
        for image in from_lines:
            assert image.startswith("python:3.13-slim"), f"non-slim base image detected: {image}"

    def test_dedicated_seerflow_user_with_pinned_uid(self, dockerfile_text: str) -> None:
        # Look for a group + user creation with uid/gid 10001
        assert re.search(r"groupadd[^\n]*--gid\s*10001[^\n]*seerflow", dockerfile_text), (
            "missing 'groupadd --gid 10001 seerflow' in Dockerfile"
        )
        assert re.search(r"useradd[^\n]*--uid\s*10001[^\n]*seerflow", dockerfile_text), (
            "missing 'useradd --uid 10001 ... seerflow' in Dockerfile"
        )
        # USER directive must switch to seerflow (the last USER instruction)
        user_lines = re.findall(r"^USER\s+(\S+)", dockerfile_text, flags=re.MULTILINE)
        assert user_lines, "no USER directive in Dockerfile"
        assert user_lines[-1] == "seerflow", (
            f"final USER must be 'seerflow', got {user_lines[-1]!r}"
        )

    def test_healthcheck_calls_health_endpoint(self, dockerfile_text: str) -> None:
        # Pull out the HEALTHCHECK block; it may span lines via backslash continuations.
        block = self._extract_healthcheck_block(dockerfile_text)
        assert block, "no HEALTHCHECK instruction in Dockerfile"
        assert "/api/v1/health" in block, "HEALTHCHECK must call the /api/v1/health endpoint"
        assert "urllib.request" in block or "urlopen" in block, (
            "HEALTHCHECK must use Python urllib (no extra apt packages)"
        )

    def test_healthcheck_has_start_period(self, dockerfile_text: str) -> None:
        block = self._extract_healthcheck_block(dockerfile_text)
        assert block, "no HEALTHCHECK instruction in Dockerfile"
        assert "--start-period=" in block, (
            "HEALTHCHECK must declare --start-period to tolerate API warm-up"
        )

    def test_no_apt_cache_left_in_layer(self, dockerfile_text: str) -> None:
        # Every apt-get install must clean /var/lib/apt/lists in the same RUN layer.
        for run_block in self._iter_run_blocks(dockerfile_text):
            if "apt-get install" not in run_block:
                continue
            assert "rm -rf /var/lib/apt/lists/*" in run_block, (
                "apt-get install must be paired with 'rm -rf /var/lib/apt/lists/*' "
                f"in the same layer; offending RUN: {run_block!r}"
            )

    def test_data_dir_owned_by_seerflow(self, dockerfile_text: str) -> None:
        assert "chown seerflow:seerflow /app/data" in dockerfile_text, (
            "/app/data must be chowned to seerflow:seerflow before USER switch"
        )

    @staticmethod
    def _extract_healthcheck_block(text: str) -> str:
        lines = text.splitlines()
        block: list[str] = []
        capturing = False
        for raw in lines:
            line = raw.rstrip()
            if not capturing and line.startswith("HEALTHCHECK"):
                capturing = True
                block.append(line)
                if not line.endswith("\\"):
                    break
                continue
            if capturing:
                block.append(line)
                if not line.endswith("\\"):
                    break
        return "\n".join(block)

    @staticmethod
    def _iter_run_blocks(text: str):
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            if line.startswith("RUN "):
                block = [line]
                while block[-1].endswith("\\") and i + 1 < len(lines):
                    i += 1
                    block.append(lines[i].rstrip())
                yield "\n".join(block)
            i += 1


class TestDockerCompose:
    def test_seerflow_service_present(self, compose_data: dict) -> None:
        assert "services" in compose_data
        assert "seerflow" in compose_data["services"], "compose must define a 'seerflow' service"

    def test_security_opt_no_new_privileges(self, compose_data: dict) -> None:
        opts = compose_data["services"]["seerflow"].get("security_opt", [])
        assert "no-new-privileges:true" in opts, (
            "compose seerflow service must set security_opt: no-new-privileges:true"
        )

    def test_drops_all_capabilities(self, compose_data: dict) -> None:
        cap_drop = compose_data["services"]["seerflow"].get("cap_drop", [])
        assert cap_drop == ["ALL"], (
            f"compose seerflow service must drop ALL caps, got {cap_drop!r}"
        )

    def test_read_only_root_fs_with_tmpfs(self, compose_data: dict) -> None:
        svc = compose_data["services"]["seerflow"]
        assert svc.get("read_only") is True, "seerflow service must set read_only: true"
        tmpfs = svc.get("tmpfs", [])
        assert any("/tmp" in entry for entry in tmpfs), (
            "seerflow service must mount /tmp as tmpfs to keep root FS read-only"
        )

    def test_resource_limits(self, compose_data: dict) -> None:
        svc = compose_data["services"]["seerflow"]
        assert svc.get("mem_limit"), "seerflow service must set mem_limit"
        assert svc.get("pids_limit"), "seerflow service must set pids_limit"

    def test_init_pid1_handling(self, compose_data: dict) -> None:
        svc = compose_data["services"]["seerflow"]
        assert svc.get("init") is True, (
            "seerflow service must request init: true to ensure proper PID 1 handling"
        )

    def test_user_pinned_to_uid_10001(self, compose_data: dict) -> None:
        svc = compose_data["services"]["seerflow"]
        user = str(svc.get("user", ""))
        assert user == "10001:10001", f"seerflow service must run as 10001:10001, got {user!r}"


class TestDockerignore:
    @pytest.mark.parametrize(
        "needle",
        [
            "dist/",
            "htmlcov/",
            ".benchmarks/",
            ".pytest_cache/",
            ".ruff_cache/",
            ".mypy_cache/",
            "benchmark-results.json",
            "frontend/node_modules/",
            ".devcontainer/",
        ],
    )
    def test_excludes_caches_and_artifacts(
        self, dockerignore_lines: list[str], needle: str
    ) -> None:
        assert needle in dockerignore_lines, (
            f".dockerignore is missing entry {needle!r}; current entries={dockerignore_lines!r}"
        )
