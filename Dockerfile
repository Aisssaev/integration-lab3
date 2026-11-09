# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.11-slim

FROM ${PYTHON_IMAGE} AS trainer
WORKDIR /build
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data HOME=/tmp USER=trainer TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libsndfile1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-api.txt requirements-train.txt ./
RUN pip install -r requirements-train.txt

COPY src/ ./src/
ENTRYPOINT ["python", "-m", "src.train"]
CMD ["--classes", "yes", "no", "up", "down", "--epochs", "10", "--seed", "42", "--out", "/artifacts"]

FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libsndfile1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-api.txt ./
RUN pip install --upgrade pip setuptools wheel && pip install -r requirements-api.txt

RUN useradd --create-home --uid 10001 appuser
COPY src/ ./src/
COPY --chown=appuser artifacts/model.pt artifacts/labels.json artifacts/metrics.json ./artifacts/

ARG MODEL_VERSION=1.0.0
ARG GIT_COMMIT=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="kws-api" \
      org.opencontainers.image.description="Keyword spotting (Speech Commands) inference API" \
      org.opencontainers.image.version="${MODEL_VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      ml.model.version="${MODEL_VERSION}"

ENV MODEL_PATH=/app/artifacts/model.pt \
    BACKEND=torch \
    PORT=8000 \
    TORCH_THREADS=2 \
    LOG_LEVEL=info \
    GIT_COMMIT=${GIT_COMMIT}

USER appuser
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/health', timeout=4)"
CMD ["sh", "-c", "exec uvicorn src.api:app --host 0.0.0.0 --port ${PORT} --log-level $(echo ${LOG_LEVEL} | tr A-Z a-z)"]
