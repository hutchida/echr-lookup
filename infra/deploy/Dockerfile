# syntax=docker/dockerfile:1.7
# One image for the FastAPI app and the MCP server (docs/hosting-options.md).
# Build context = repo root:  docker build -f infra/deploy/Dockerfile --target runtime-baked .
#
# Targets:
#   runtime-baked  (default, last stage)  embedder + reranker inside the image, works offline
#   runtime-slim                          no models; they download into the HF_HOME volume on first start

# ---- 1. dependencies: CPU-only torch (the lockfile points linux at the pytorch-cpu index) ----
FROM python:3.12-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:0.9.0 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/py/.venv
WORKDIR /app/py
COPY py/pyproject.toml py/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group ml

# ---- 2. models: only the files the code loads (no onnx/openvino variants) ----
FROM deps AS models
ENV HF_HOME=/models
RUN /app/py/.venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("BAAI/bge-small-en-v1.5", allow_patterns=[
    "*.json", "*.txt", "model.safetensors", "1_Pooling/*"])
snapshot_download("BAAI/bge-reranker-base", allow_patterns=[
    "*.json", "model.safetensors", "sentencepiece.bpe.model"])
PY

# ---- 3. runtime without models ----
FROM python:3.12-slim AS runtime-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /app/py
ENV PATH=/app/py/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/models DATA_SOURCE=snapshot
COPY --from=deps /app/py/.venv /app/py/.venv
# rag.config derives REPO_ROOT from its own path, so keep the repo layout under /app.
COPY py/ /app/py/
COPY infra/migrations/ /app/infra/migrations/
COPY config/ /app/config/
COPY data/snapshot/ /app/data/snapshot/
COPY packages/contract/schema/ /app/packages/contract/schema/
COPY packages/contract/fixtures/ /app/packages/contract/fixtures/
RUN mkdir -p /models && chown app /models
USER app
EXPOSE 8000 8100
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- 4. runtime with models baked in (default) ----
FROM runtime-slim AS runtime-baked
COPY --from=models --chown=app /models /models
ENV HF_HUB_OFFLINE=1
