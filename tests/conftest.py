import io
import os
from pathlib import Path

import numpy as np
import pytest
import requests
import soundfile as sf

API_URL = os.environ.get("API_URL", "http://localhost:8000")
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
CLASSES = ("yes", "no", "up", "down")


def wav_bytes(samples: np.ndarray, sr: int = 16_000, fmt: str = "WAV") -> bytes:
    buf = io.BytesIO()
    sf.write(buf, samples, sr, format=fmt)
    return buf.getvalue()


def post_audio(data: bytes, name: str = "sample.wav", **params) -> requests.Response:
    return requests.post(f"{API_URL}/predict", files={"file": (name, data, "audio/wav")}, params=params, timeout=10)


@pytest.fixture(scope="session")
def api_url() -> str:
    return API_URL


@pytest.fixture(scope="session")
def samples() -> list[tuple[str, bytes]]:
    """(істинний клас, байти) для samples/<клас>_<n>.wav."""
    return [(p.stem.split("_")[0], p.read_bytes()) for p in sorted(SAMPLES_DIR.glob("*.wav"))]


@pytest.fixture(scope="session")
def yes_sample() -> bytes:
    return (SAMPLES_DIR / "yes_1.wav").read_bytes()
