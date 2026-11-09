"""Навчання + оцінка + експорт артефактів (model.pt, model.onnx, labels.json, metrics.json, history.json).

python -m src.train --classes yes no up down --epochs 15 --seed 42 --out artifacts
"""
import argparse
import json
import os
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from src.config import DATA_DIR, DEFAULT_CLASSES
from src.data import load_wav, log_mel, split_files
from src.download import download
from src.evaluate import evaluate
from src.inference import TorchPredictor
from src.model import ARCHITECTURE, KeywordCNN, count_parameters

BATCH_SIZE = 128
LR = 3e-3
LATENCY_RUNS = 200


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def build_features(root: Path, files: list[tuple[str, int]]) -> tuple[torch.Tensor, torch.Tensor]:
    """Лог-Mel для всього спліту, обчислюється один раз пакетами."""
    waves = np.stack([load_wav(root / rel) for rel, _ in files])
    feats = np.concatenate([log_mel(chunk) for chunk in np.array_split(waves, max(1, len(waves) // 1024))])
    return torch.from_numpy(feats), torch.tensor([label for _, label in files])


def spec_augment(x: torch.Tensor) -> torch.Tensor:
    """Зсув у часі ±100 мс + маскування однієї смуги частот (≤8) і часу (≤15) на приклад."""
    x = torch.roll(x, shifts=random.randint(-10, 10), dims=-1).clone()
    b, n_mels, n_frames = x.shape
    for i in range(b):
        f = random.randint(0, 8)
        f0 = random.randint(0, n_mels - f)
        t = random.randint(0, 15)
        t0 = random.randint(0, n_frames - t)
        x[i, f0 : f0 + f, :] = 0
        x[i, :, t0 : t0 + t] = 0
    return x


def run_epoch(model, loader, criterion, optimizer=None, scheduler=None) -> tuple[float, float]:
    training = optimizer is not None
    model.train(training)
    total_loss, correct, seen = 0.0, 0, 0
    with torch.set_grad_enabled(training):
        for x, y in loader:
            if training:
                x = spec_augment(x)
            logits = model(x)
            loss = criterion(logits, y)
            if training:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                scheduler.step()
            total_loss += loss.item() * len(y)
            correct += (logits.argmax(1) == y).sum().item()
            seen += len(y)
    return total_loss / seen, correct / seen


class ExportWrapper(nn.Module):
    """Модель для ONNX: нормалізація + CNN + softmax в одному графі."""

    def __init__(self, model: nn.Module, mean: float, std: float) -> None:
        super().__init__()
        self.model, self.mean, self.std = model, mean, std

    def forward(self, logmel: torch.Tensor) -> torch.Tensor:
        return torch.softmax(self.model((logmel - self.mean) / self.std), dim=-1)


def export_onnx(model: nn.Module, mean: float, std: float, path: Path, example: torch.Tensor) -> None:
    torch.onnx.export(
        ExportWrapper(model, mean, std).eval(), (example,), str(path),
        input_names=["logmel"], output_names=["probs"],
        dynamic_axes={"logmel": {0: "batch"}, "probs": {0: "batch"}}, opset_version=17, dynamo=False,
    )


def measure_latency(predictor: TorchPredictor, payloads: list[bytes]) -> dict[str, float]:
    for data in payloads[:20]:
        predictor.predict_bytes(data)
    values = sorted(predictor.predict_bytes(payloads[i % len(payloads)]).latency_ms for i in range(LATENCY_RUNS))
    return dict(mean=statistics.fmean(values), p50=values[len(values) // 2], p95=values[int(0.95 * (len(values) - 1))])


def main() -> None:
    parser = argparse.ArgumentParser(description="Навчання KeywordCNN")
    parser.add_argument("--classes", nargs="+", default=list(DEFAULT_CLASSES))
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--out", type=Path, default=Path("artifacts"))
    parser.add_argument("--model-version", default=os.environ.get("MODEL_VERSION", "1.0.0"))
    args = parser.parse_args()

    classes = tuple(args.classes)
    seed_everything(args.seed)
    torch.set_num_threads(os.cpu_count() or 4)
    args.out.mkdir(parents=True, exist_ok=True)

    root = download(args.data_dir, classes)
    splits = split_files(root, classes)
    print({k: len(v) for k, v in splits.items()}, flush=True)

    t0 = time.time()
    train_x, train_y = build_features(root, splits["train"])
    val_x, val_y = build_features(root, splits["val"])
    print(f"Спектрограми: {time.time() - t0:.1f} с, форма {tuple(train_x.shape)}", flush=True)
    mean, std = train_x.mean().item(), train_x.std().item()
    train_x, val_x = (train_x - mean) / std, (val_x - mean) / std

    generator = torch.Generator().manual_seed(args.seed)
    train_loader = DataLoader(TensorDataset(train_x, train_y), batch_size=BATCH_SIZE, shuffle=True, generator=generator)
    val_loader = DataLoader(TensorDataset(val_x, val_y), batch_size=512)

    model = KeywordCNN(len(classes))
    print(f"{ARCHITECTURE}; параметрів: {count_parameters(model):,}", flush=True)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.05)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-3)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(optimizer, max_lr=LR, epochs=args.epochs,
                                                    steps_per_epoch=len(train_loader))

    model_path = args.out / "model.pt"
    history, best_acc, t_train = [], -1.0, time.time()
    for epoch in range(1, args.epochs + 1):
        tr_loss, tr_acc = run_epoch(model, train_loader, criterion, optimizer, scheduler)
        va_loss, va_acc = run_epoch(model, val_loader, criterion)
        history.append(dict(epoch=epoch, train_loss=tr_loss, train_acc=tr_acc, val_loss=va_loss, val_acc=va_acc))
        print(f"epoch {epoch:2d} | train {tr_loss:.4f}/{tr_acc:.4f} | val {va_loss:.4f}/{va_acc:.4f}", flush=True)
        if va_acc > best_acc:
            best_acc = va_acc
            torch.save(dict(state_dict=model.state_dict(), classes=list(classes), mean=mean, std=std,
                            model_version=args.model_version, epoch=epoch), model_path)
    train_time = time.time() - t_train

    predictor = TorchPredictor(model_path, threads=2)
    export_onnx(predictor.model, mean, std, args.out / "model.onnx", val_x[:1] * std + mean)
    result = evaluate(predictor, root)
    payloads = [(root / rel).read_bytes() for rel, _ in splits["test"][:100]]
    metrics = dict(
        model_version=args.model_version,
        architecture=ARCHITECTURE,
        classes=list(classes),
        parameters=count_parameters(predictor.model),
        model_size_kb=round(model_path.stat().st_size / 1024, 1),
        onnx_size_kb=round((args.out / "model.onnx").stat().st_size / 1024, 1),
        accuracy=result["accuracy"],
        per_class_accuracy=result["per_class_accuracy"],
        confusion_matrix=result["confusion_matrix"],
        test_samples=result["test_samples"],
        best_val_accuracy=round(100 * best_acc, 2),
        latency_ms=measure_latency(predictor, payloads),
        epochs=args.epochs,
        seed=args.seed,
        split_sizes={k: len(v) for k, v in splits.items()},
        train_time_s=round(train_time, 1),
        trained_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        torch_version=torch.__version__,
        git_commit=os.environ.get("GIT_COMMIT", "unknown"),
    )
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    (args.out / "labels.json").write_text(json.dumps(dict(classes=list(classes), model_version=args.model_version)))
    (args.out / "history.json").write_text(json.dumps(history, indent=2))
    print(json.dumps({k: metrics[k] for k in ("accuracy", "model_size_kb", "latency_ms")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
