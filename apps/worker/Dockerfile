FROM ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c AS uv

FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8 AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
COPY packages/platform-core/pyproject.toml packages/platform-core/pyproject.toml
COPY apps/api/src apps/api/src
COPY apps/worker/src apps/worker/src
COPY packages/platform-core/src packages/platform-core/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
      --frozen \
      --no-dev \
      --no-editable \
      --package agreement-intelligence-worker

FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8 AS runtime
ENV PATH=/workspace/.venv/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV WORKER_HEARTBEAT_PATH=/tmp/agreement-worker-heartbeat
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app
WORKDIR /workspace
COPY --from=build --chown=app:app /workspace/.venv /workspace/.venv
USER app
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=12 \
  CMD ["python", "-c", "import os,sys,time; age=time.time()-os.path.getmtime(os.environ['WORKER_HEARTBEAT_PATH']); sys.exit(0 if age < 15 else 1)"]
CMD ["agreement-worker"]
