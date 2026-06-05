# syntax=docker/dockerfile:1

# ---- builder: install the package and its full dependency set ---------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Copy only what's needed to resolve and build the wheel first, for layer cache.
COPY pyproject.toml README.md ./
COPY mutagen ./mutagen

# Build a wheel and install it (with all integrations) into a venv we copy over.
RUN python -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --upgrade pip build \
    && pip install ".[all]"

# ---- runtime: slim image with git (for cloning target repos) ----------------
FROM python:3.12-slim AS runtime

# git is required to ingest remote repositories; clean up apt lists after.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Run as a non-root user; mount a workspace for inputs/outputs.
RUN useradd --create-home --uid 1000 mutagen
USER mutagen
WORKDIR /workspace

# ANTHROPIC_API_KEY must be provided at runtime, e.g.:
#   docker run --rm -e ANTHROPIC_API_KEY=... -v "$PWD:/workspace" mutagen run .
ENTRYPOINT ["mutagen"]
CMD ["--help"]
