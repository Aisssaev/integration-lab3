#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

EPOCHS=${EPOCHS:-2}
SEED=${SEED:-42}
MIN_ACCURACY=${MIN_ACCURACY:-85}
PY=${PY:-python3}
IMAGE=kws-api:ci

step() { printf '\n==== %s ====\n' "$1"; }
cleanup() { docker rm -f kws >/dev/null 2>&1 || true; }
trap cleanup EXIT

step "train (epochs=$EPOCHS)"
docker build -q --target trainer -t kws-trainer:ci .
rm -rf artifacts metrics && mkdir -p artifacts data metrics
docker run --rm --user "$(id -u):$(id -g)" -e GIT_COMMIT=local \
  -v "$PWD/data/:/data" -v "$PWD/artifacts:/artifacts" kws-trainer:ci \
  --classes yes no up down --epochs "$EPOCHS" --seed "$SEED" --model-version 1.0.0+local \
  --out /artifacts 2>&1 | tee artifacts/train.log

step "verify"
docker build -q --target runtime --build-arg GIT_COMMIT=local --build-arg MODEL_VERSION=1.0.0+local -t "$IMAGE" .
cleanup
docker run -d --name kws -p 8000:8000 "$IMAGE" >/dev/null
for _ in $(seq 1 30); do curl -sf http://localhost:8000/health && break; sleep 2; done
echo
"$PY" scripts/verify_model.py --url http://localhost:8000 --expected samples/expected.json --out metrics/verify.json
curl -sf http://localhost:8000/model-info | tee metrics/model-info.json
echo
jq -e ".accuracy >= $MIN_ACCURACY" metrics/model-info.json
"$PY" scripts/benchmark.py --url http://localhost:8000 --n 100 --warmup 10 --out metrics/latency.json >/dev/null
MIN_ACCURACY=$MIN_ACCURACY "$PY" scripts/make_report.py --metrics metrics/ --model artifacts/metrics.json --out metrics/report.md

step "integration tests"
API_URL=http://localhost:8000 "$PY" -m pytest -q tests/ --junitxml=metrics/junit.xml
