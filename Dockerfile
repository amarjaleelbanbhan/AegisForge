# CortexWard container image.
# Multi-stage build: a builder syncs the full uv workspace into a
# non-editable virtualenv, and a slim, non-root runtime stage carries only
# that venv plus the `ward` entry point -- no source tree, no dev tooling.

# --- Builder ---------------------------------------------------------------
FROM python:3.12-slim AS builder

# uv provides fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Workspace member packages resolve their sibling dependencies via
# `{ workspace = true }` sources (ADR-0005), so the whole workspace
# manifest + lockfile + every member's pyproject.toml must be present for
# `uv sync` to resolve at all -- copying just cortexward-cli's own
# directory in isolation, the way this file did before cortexward-cli
# existed, is not enough once it has workspace-local dependencies.
COPY pyproject.toml uv.lock ./
COPY packages ./packages

# --package cortexward-cli pulls in only that package and its transitive
# dependencies (still every workspace member it actually needs, e.g.
# cortexward-orchestrator, -server), not every unrelated workspace member.
# --no-dev excludes ruff/mypy/pytest and friends -- this is a runtime
# image, not a dev environment. --no-editable is required correctness,
# not an optimization: uv sync's default editable install for workspace
# members writes a .pth file pointing back at this source tree, which the
# runtime stage below never copies -- an editable install would fail to
# import at all once /opt/venv is the only thing carried over.
RUN uv sync --frozen --no-dev --no-editable --package cortexward-cli

# --- Runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Run as an unprivileged user. CortexWard analyzes untrusted code; the process
# should hold no more privilege than it needs.
RUN groupadd --gid 10001 cortex \
    && useradd --uid 10001 --gid cortex --create-home --shell /usr/sbin/nologin cortex

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv

USER cortex
WORKDIR /workspace

ENTRYPOINT ["ward"]
CMD ["--help"]
