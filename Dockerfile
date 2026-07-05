# CortexWard container image.
# Multi-stage build: a builder installs the package into a virtualenv, and a
# slim, non-root runtime stage carries only what is needed to run.

# --- Builder ---------------------------------------------------------------
FROM python:3.12-slim AS builder

# uv provides fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Create the venv, then install the package. cortexward-core is
# self-contained (its own pyproject.toml, README, SPDX license identifier)
# so it builds without the workspace root manifest (ADR-0005). As sibling
# packages (cortexward-cli, cortexward-server, ...) are implemented, add
# their COPY + install lines here too.
RUN uv venv "$VIRTUAL_ENV"
COPY packages/cortexward-core ./cortexward-core
RUN uv pip install ./cortexward-core

# --- Runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Run as an unprivileged user. CortexWard analyzes untrusted code; the process
# should hold no more privilege than it needs.
RUN groupadd --gid 10001 cortex \
    && useradd --uid 10001 --gid cortex --create-home --shell /usr/sbin/nologin cortex

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv

USER cortex
WORKDIR /workspace

# Sanity check on build; replaced by the CLI entry point in a later phase.
CMD ["python", "-c", "from cortexward.core import version; print('CortexWard', version())"]
