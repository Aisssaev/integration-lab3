"""Інтеграційні тести API, що працює в контейнері (pytest + requests). Запуск: API_URL=... pytest tests"""
import math
import statistics
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
import soundfile as sf

from conftest import CLASSES, SAMPLES_DIR, post_audio, wav_bytes

P95_LIMIT_MS = 50
RNG = np.random.default_rng(0)


def test_health(api_url):
    r = requests.get(f"{api_url}/health", timeout=5)
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_model_info_schema(api_url):
    info = requests.get(f"{api_url}/model-info", timeout=5).json()
    assert info["classes"] == list(CLASSES)
    assert 0 < info["model_size_kb"] < 5 * 1024
    assert 0 <= info["accuracy"] <= 100  # у відсотках
    assert info["model_version"]


def test_predict_schema(yes_sample):
    r = post_audio(yes_sample)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"label", "confidence", "probabilities", "latency_ms", "model_version"}
    assert body["label"] in CLASSES and body["latency_ms"] > 0


def test_probabilities_distribution(yes_sample):
    body = post_audio(yes_sample).json()
    assert math.isclose(sum(body["probabilities"].values()), 1.0, abs_tol=1e-3)
    assert body["confidence"] == max(body["probabilities"].values())


def test_samples_predicted_correctly(samples):
    correct = sum(post_audio(data).json()["label"] == truth for truth, data in samples)
    assert correct / len(samples) >= 0.75


def test_version_consistent(api_url, yes_sample):
    info = requests.get(f"{api_url}/model-info", timeout=5).json()
    assert post_audio(yes_sample).json()["model_version"] == info["model_version"]


def test_spectrogram_shape(yes_sample):
    spec = post_audio(yes_sample, return_spectrogram="true").json()["spectrogram"]
    assert len(spec) == 64 and all(len(row) == 101 for row in spec)


def test_other_sample_rate_and_stereo():
    samples, _ = sf.read(SAMPLES_DIR / "no_1.wav")
    down = samples[::2].astype(np.float32)  # 8 кГц
    assert post_audio(wav_bytes(down, sr=8000)).status_code == 200
    stereo = RNG.normal(0, 0.05, size=(8000, 2)).astype(np.float32)
    assert post_audio(wav_bytes(stereo)).status_code == 200


def test_invalid_file_returns_400():
    for payload in (b"", b"not a wav file" * 20):
        r = post_audio(payload)
        assert r.status_code == 400 and "detail" in r.json()


def test_too_long_audio_returns_400():
    long_audio = RNG.normal(0, 0.01, size=16_000 * 12).astype(np.float32)
    assert post_audio(wav_bytes(long_audio, fmt="FLAC"), name="long.flac").status_code == 400


def test_oversized_and_missing_file(api_url):
    assert post_audio(b"\0" * 1_100_000).status_code == 413
    assert requests.post(f"{api_url}/predict", timeout=5).status_code == 422


def test_concurrent_requests(yes_sample):
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: post_audio(yes_sample), range(32)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["label"] for r in responses}) == 1


def test_latency_p95_within_limit(yes_sample):
    values = sorted(post_audio(yes_sample).json()["latency_ms"] for _ in range(40))
    assert values[int(0.95 * (len(values) - 1))] < P95_LIMIT_MS
    assert statistics.fmean(values) < P95_LIMIT_MS
