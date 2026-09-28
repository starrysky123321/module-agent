FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 module-agent \
    && useradd --uid 10001 --gid 10001 --no-create-home module-agent \
    && mkdir -p /var/lib/module-agent/code-workspaces /tmp/uv-cache \
    && chown -R 10001:10001 /var/lib/module-agent /tmp/uv-cache

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache \
    PYTHONPATH=/app/src

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev

COPY --chown=10001:10001 src ./src
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 alembic.ini ./

USER 10001:10001

CMD ["uv", "run", "--no-sync", "python", "-m", "module_agent.cli.run_literature_worker"]
