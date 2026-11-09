"""Інференс: спільний препроцесинг (NumPy) + бекенд PyTorch або ONNX Runtime.

Модулі бекендів імпортуються ліниво, тому ONNX-образ не потребує PyTorch.
"""
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.data import decode_audio, log_mel


@dataclass(frozen=True)
class Prediction:
    label: str
    confidence: float
    probabilities: dict[str, float]
    latency_ms: float  # препроцесинг + інференс
    spectrogram: np.ndarray  # лог-Mel [N_MELS, frames]


class Predictor:
    """Базовий клас: препроцесинг і вимір затримки; підкласи реалізують _probs()."""

    classes: list[str]
    version: str
    backend: str
    model_path: Path

    def _probs(self, spec: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def predict_bytes(self, data: bytes) -> Prediction:
        start = time.perf_counter()
        spec = log_mel(decode_audio(data))
        probs = self._probs(spec)
        latency_ms = (time.perf_counter() - start) * 1000
        idx = int(probs.argmax())
        return Prediction(
            label=self.classes[idx],
            confidence=float(probs[idx]),
            probabilities={c: float(p) for c, p in zip(self.classes, probs)},
            latency_ms=latency_ms,
            spectrogram=spec,
        )


class TorchPredictor(Predictor):
    backend = "torch"

    def __init__(self, model_path: Path, threads: int | None = None) -> None:
        import torch

        from src.model import KeywordCNN

        if threads:
            torch.set_num_threads(threads)
        ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
        self.classes = list(ckpt["classes"])
        self.version = ckpt["model_version"]
        self.mean, self.std = ckpt["mean"], ckpt["std"]
        self.model = KeywordCNN(len(self.classes))
        self.model.load_state_dict(ckpt["state_dict"])
        self.model.eval()
        self.model_path = Path(model_path)
        self._torch = torch

    def _probs(self, spec: np.ndarray) -> np.ndarray:
        torch = self._torch
        with torch.inference_mode():
            x = torch.from_numpy((spec - self.mean) / self.std).unsqueeze(0)
            return torch.softmax(self.model(x)[0], dim=0).numpy()


class OnnxPredictor(Predictor):
    """ONNX-граф уже містить нормалізацію та softmax."""

    backend = "onnx"

    def __init__(self, model_path: Path, threads: int | None = None) -> None:
        import onnxruntime as ort

        meta = json.loads((Path(model_path).parent / "labels.json").read_text())
        self.classes, self.version = meta["classes"], meta["model_version"]
        options = ort.SessionOptions()
        if threads:
            options.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])
        self.model_path = Path(model_path)

    def _probs(self, spec: np.ndarray) -> np.ndarray:
        return self.session.run(None, {"logmel": spec[None].astype(np.float32)})[0][0]


def load_predictor(model_path: Path, backend: str = "torch", threads: int | None = None) -> Predictor:
    backends = {"torch": TorchPredictor, "onnx": OnnxPredictor}
    if backend not in backends:
        raise ValueError(f"невідомий BACKEND={backend!r}, очікується одне з {sorted(backends)}")
    return backends[backend](model_path, threads)
