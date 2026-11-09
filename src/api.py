"""FastAPI-сервіс інференсу. Конфігурація — змінні середовища MODEL_PATH, BACKEND, TORCH_THREADS, LOG_LEVEL."""
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from src.config import BACKEND, GIT_COMMIT, LOG_LEVEL, MAX_UPLOAD_BYTES, MODEL_PATH, TORCH_THREADS
from src.data import AudioDecodeError
from src.inference import Predictor, load_predictor

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("kws.api")


class PredictResponse(BaseModel):
    label: str
    confidence: float
    probabilities: dict[str, float]
    latency_ms: float
    model_version: str
    spectrogram: list[list[float]] | None = None


state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Модель завантажується один раз під час старту, а не на кожен запит.
    try:
        state["predictor"] = load_predictor(MODEL_PATH, BACKEND, TORCH_THREADS)
        log.info("модель %s (%s) завантажено з %s", state["predictor"].version, BACKEND, MODEL_PATH)
    except FileNotFoundError:
        log.error("файл моделі не знайдено: %s", MODEL_PATH)
    yield
    state.clear()


app = FastAPI(title="KWS API", version="3.0.0", lifespan=lifespan)


def predictor() -> Predictor:
    if "predictor" not in state:
        raise HTTPException(status_code=503, detail=f"модель не завантажена ({MODEL_PATH})")
    return state["predictor"]


@app.get("/health")
def health() -> dict:
    if "predictor" not in state:
        raise HTTPException(status_code=503, detail="model not loaded")
    return {"status": "ok"}


@app.get("/model-info")
def model_info() -> dict:
    p = predictor()
    metrics_path = p.model_path.parent / "metrics.json"
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    return {
        "model_version": p.version,
        "backend": p.backend,
        "architecture": metrics.get("architecture"),
        "classes": p.classes,
        "parameters": metrics.get("parameters"),
        "model_size_kb": round(p.model_path.stat().st_size / 1024, 1),
        "accuracy": metrics.get("accuracy"),  # у відсотках
        "trained_at": metrics.get("trained_at"),
        "epochs": metrics.get("epochs"),
        "seed": metrics.get("seed"),
        "git_commit": GIT_COMMIT,
    }


@app.post("/predict", response_model=PredictResponse, response_model_exclude_none=True)
def predict(
    file: UploadFile = File(..., description="WAV/FLAC/OGG, бажано 16 кГц моно, до 10 с"),
    return_spectrogram: bool = Query(False, description="повернути лог-Mel-спектрограму"),
) -> PredictResponse:
    p = predictor()
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"файл більший за {MAX_UPLOAD_BYTES} байт")
    if not data:
        raise HTTPException(status_code=400, detail="порожній файл")
    try:
        result = p.predict_bytes(data)
    except AudioDecodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PredictResponse(
        label=result.label,
        confidence=round(result.confidence, 4),
        probabilities={k: round(v, 4) for k, v in result.probabilities.items()},
        latency_ms=round(result.latency_ms, 3),
        model_version=p.version,
        spectrogram=result.spectrogram.tolist() if return_spectrogram else None,
    )
