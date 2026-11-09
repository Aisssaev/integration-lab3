"""Дані та попередня обробка: поділ датасету, декодування аудіо, лог-Mel-спектрограми.

Mel-спектрограма реалізована на NumPy (STFT з вікном Ганна + HTK Mel-фільтри, як у
torchaudio.transforms.MelSpectrogram за замовчуванням). Тому один і той самий код
препроцесингу працює і з PyTorch, і з ONNX Runtime, без залежності від torchaudio.
"""
import io
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from src.config import HOP_LENGTH, MAX_DURATION_S, N_FFT, N_MELS, NUM_SAMPLES, SAMPLE_RATE


class AudioDecodeError(ValueError):
    """Вхідні байти не є коректним аудіо або порушують обмеження."""


# ---------- поділ датасету ----------
def split_files(root: Path, classes: tuple[str, ...]) -> dict[str, list[tuple[str, int]]]:
    """Офіційний поділ: validation_list / testing_list / решта — train."""

    def read_list(name: str) -> set[str]:
        return {line for line in (root / name).read_text().splitlines() if line.split("/", 1)[0] in classes}

    val, test = read_list("validation_list.txt"), read_list("testing_list.txt")
    splits: dict[str, list[tuple[str, int]]] = {"train": [], "val": [], "test": []}
    for label, cls in enumerate(classes):
        for wav in sorted((root / cls).glob("*.wav")):
            rel = f"{cls}/{wav.name}"
            split = "val" if rel in val else "test" if rel in test else "train"
            splits[split].append((rel, label))
    return splits


# ---------- аудіо ----------
def decode_audio(data: bytes) -> np.ndarray:
    """Байти аудіофайлу -> моно-хвиля 16 кГц рівно 1 с (float32 [NUM_SAMPLES])."""
    try:
        samples, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception as exc:  # soundfile кидає різні типи помилок
        raise AudioDecodeError(f"не вдалося декодувати аудіо: {exc}") from exc
    if samples.size == 0:
        raise AudioDecodeError("аудіо не містить семплів")
    if samples.shape[0] / sr > MAX_DURATION_S:
        raise AudioDecodeError(f"аудіо довше за {MAX_DURATION_S:.0f} с")
    wave = samples.mean(axis=1)
    if sr != SAMPLE_RATE:  # лінійна інтерполяція — достатньо для мовних команд
        n_out = int(round(len(wave) * SAMPLE_RATE / sr))
        wave = np.interp(np.linspace(0, len(wave) - 1, n_out), np.arange(len(wave)), wave).astype(np.float32)
    return fit_length(wave)


def fit_length(wave: np.ndarray) -> np.ndarray:
    """Доповнює нулями або вирізає центральну 1 с."""
    n = wave.shape[-1]
    if n < NUM_SAMPLES:
        return np.pad(wave, (0, NUM_SAMPLES - n))
    start = (n - NUM_SAMPLES) // 2
    return wave[start : start + NUM_SAMPLES]


def load_wav(path: Path) -> np.ndarray:
    return decode_audio(Path(path).read_bytes())


# ---------- Mel-спектрограма ----------
@lru_cache(maxsize=1)
def mel_filterbank() -> np.ndarray:
    """HTK Mel-фільтри [n_fft//2+1, N_MELS] (еквівалент torchaudio melscale_fbanks)."""
    all_freqs = np.linspace(0, SAMPLE_RATE // 2, N_FFT // 2 + 1)
    hz_to_mel = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)  # noqa: E731
    m_pts = np.linspace(hz_to_mel(0.0), hz_to_mel(SAMPLE_RATE / 2), N_MELS + 2)
    f_pts = 700.0 * (10 ** (m_pts / 2595.0) - 1.0)
    f_diff = f_pts[1:] - f_pts[:-1]
    slopes = f_pts[None, :] - all_freqs[:, None]
    down = -slopes[:, :-2] / f_diff[:-1]
    up = slopes[:, 2:] / f_diff[1:]
    return np.maximum(0.0, np.minimum(down, up)).astype(np.float32)


@lru_cache(maxsize=1)
def _window() -> np.ndarray:
    return (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)  # periodic Hann


def log_mel(waves: np.ndarray) -> np.ndarray:
    """Хвилі [..., NUM_SAMPLES] -> лог-Mel [..., N_MELS, 101]."""
    pad = N_FFT // 2
    padded = np.pad(waves, [(0, 0)] * (waves.ndim - 1) + [(pad, pad)], mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, N_FFT, axis=-1)[..., ::HOP_LENGTH, :]
    spectrum = np.fft.rfft(frames * _window(), axis=-1)  # [..., frames, freq]
    power = (spectrum.real**2 + spectrum.imag**2).astype(np.float32)
    # 2D-матмноження йде через BLAS; пакетне 3D у NumPy — у ~100 разів повільніше
    mel = (power.reshape(-1, power.shape[-1]) @ mel_filterbank()).reshape(*power.shape[:-1], -1)
    return np.log(np.swapaxes(mel, -1, -2) + 1e-6)
