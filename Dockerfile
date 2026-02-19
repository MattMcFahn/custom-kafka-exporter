FROM python:3.13-slim AS system

ENV DEBIAN_FRONTEND=noninteractive
ENV UV_SYSTEM_PYTHON=1
ENV PYTHONUNBUFFERED=1
ENV UV_NO_DEV=1

# System deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv (single binary)
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
COPY app/ /app

# Sync the project into a new environment, asserting the lockfile is up to date
WORKDIR /app
RUN uv sync --locked

EXPOSE 8000

ENTRYPOINT ["uv", "run", "-m", "app"]
