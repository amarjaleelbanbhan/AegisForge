# AegisForge container image.
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

# Create the venv, then install dependencies first (better layer caching),
# then the project itself.
RUN uv venv "$VIRTUAL_ENV"
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN uv pip install .

# --- Runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Run as an unprivileged user. AegisForge analyzes untrusted code; the process
# should hold no more privilege than it needs.
RUN groupadd --gid 10001 aegis \
    && useradd --uid 10001 --gid aegis --create-home --shell /usr/sbin/nologin aegis

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv

USER aegis
WORKDIR /workspace

# Sanity check on build; replaced by the CLI entry point in a later phase.
CMD ["python", "-c", "import aegisforge; print('AegisForge', aegisforge.__version__)"]
