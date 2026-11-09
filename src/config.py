"""Константи моделі та конфігурація через змінні середовища."""
import os
from pathlib import Path

DEFAULT_CLASSES = ("yes", "no", "up", "down")

SAMPLE_RATE = 16_000
NUM_SAMPLES = SAMPLE_RATE  # кліпи по 1 с
N_FFT = 400  # вікно 25 мс
HOP_LENGTH = 160  # крок 10 мс
N_MELS = 64
N_FRAMES = 1 + NUM_SAMPLES // HOP_LENGTH  # 101

MAX_UPLOAD_BYTES = 1_000_000
MAX_DURATION_S = 10.0

DATASET_URL = "http://download.tensorflow.org/data/speech_commands_v0.02.tar.gz"


def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


DATA_DIR = env_path("DATA_DIR", "data")
MODEL_PATH = env_path("MODEL_PATH", "artifacts/model.pt")
BACKEND = os.environ.get("BACKEND", "torch")  # torch | onnx
TORCH_THREADS = int(os.environ.get("TORCH_THREADS", 2))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()
GIT_COMMIT = os.environ.get("GIT_COMMIT", "unknown")
