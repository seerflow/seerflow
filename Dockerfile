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

# Install tini for proper PID 1 signal handling
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# Copy only the venv from builder (no uv, no build tools, no source —
# the package is installed as a wheel inside .venv/lib/python3.13/site-packages/)
COPY --from=builder /app/.venv /app/.venv

# Put the venv on PATH so "seerflow" command is available
ENV PATH="/app/.venv/bin:$PATH"

# Run as non-root
USER nobody

# Ports: HTTP API, OTLP gRPC, OTLP HTTP, syslog UDP
EXPOSE 8080 4317 4318 514/udp

# Health check: verify the process is alive (interim until /api/v1/health exists)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["seerflow", "--version"]

# tini as init process, seerflow as main command
ENTRYPOINT ["tini", "--"]
CMD ["seerflow", "start"]
