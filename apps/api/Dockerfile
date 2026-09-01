FROM ghcr.io/astral-sh/uv:0.12.8@sha256:d1cbaeadc234fe19c0d93daabcf5e98738cd93c6d1dd4918ef6aa30735feb23a AS uv

FROM python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f AS build
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
      --package agreement-intelligence-api

FROM python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f AS runtime
ENV PATH=/workspace/.venv/bin:$PATH
ENV PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app
WORKDIR /workspace
COPY --from=build --chown=app:app /workspace/.venv /workspace/.venv
COPY --chown=app:app apps/api/alembic.ini apps/api/alembic.ini
COPY --chown=app:app apps/api/migrations apps/api/migrations
USER app
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=12 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).read()"]
CMD ["uvicorn", "agreement_intelligence_api.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
