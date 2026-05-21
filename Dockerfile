# ---------------------------------------------------------------------------
# Stage 1: install dependencies with uv
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

WORKDIR /app

# Install uv from the official image (no pip needed in builder)
COPY --from=ghcr.io/astral-sh/uv:0.7.3 /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock README.md ./

# Copy source (needed for uv sync with the project itself)
COPY src/ src/

# Install all runtime deps into .venv (no dev deps, no editable install)
RUN uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------------------
# Stage 2: minimal runtime image
# ---------------------------------------------------------------------------
FROM python:3.13-slim

WORKDIR /app

# Install tini for proper PID 1 signal handling and create the dedicated
# non-root user in a single layer (no apt cache leakage).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 seerflow \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app --no-create-home --shell /usr/sbin/nologin seerflow

# Copy only the venv from builder (no uv, no build tools, no source —
# the package is installed as a wheel inside .venv/lib/python3.13/site-packages/).
# Chown to seerflow so the runtime user can read but never write the venv.
COPY --from=builder --chown=seerflow:seerflow /app/.venv /app/.venv

# Put the venv on PATH so "seerflow" command is available
ENV PATH="/app/.venv/bin:$PATH"

# Create data directory writable by seerflow (everything else is read-only
# when the container is launched with `--read-only`).
RUN mkdir -p /app/data && chown seerflow:seerflow /app/data

# Run as the dedicated non-root user
USER seerflow

# Ports: HTTP API, OTLP gRPC, OTLP HTTP, syslog UDP
EXPOSE 8080 4317 4318 514/udp

# Health check: probe the comprehensive /api/v1/health endpoint (S-080).
# Uses Python urllib so we don't have to install curl/wget. 200 = healthy,
# anything else = unhealthy. --start-period gives the API time to warm up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=3).status == 200 else 1)"]

# tini as init process, seerflow as main command
ENTRYPOINT ["tini", "--"]
CMD ["seerflow", "start"]
