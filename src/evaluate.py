"""Accuracy на тестовому наборі через повний конвеєр інференсу.

Локально:   python -m src.evaluate --data-dir data
У Docker:   docker exec kws python -m src.evaluate --data-dir /data
"""
import argparse
import json
import os
from pathlib import Path

from src.config import BACKEND, DATA_DIR, MODEL_PATH, TORCH_THREADS
from src.data import split_files
from src.inference import Predictor, load_predictor


def evaluate(predictor: Predictor, root: Path) -> dict:
    test = split_files(root, tuple(predictor.classes))["test"]
    n = len(predictor.classes)
    confusion = [[0] * n for _ in range(n)]
    for rel, label in test:
        pred = predictor.predict_bytes((root / rel).read_bytes()).label
        confusion[label][predictor.classes.index(pred)] += 1
    correct = sum(confusion[i][i] for i in range(n))
    return dict(
        test_samples=len(test),
        accuracy=round(100 * correct / len(test), 2),
        per_class_accuracy={c: round(100 * confusion[i][i] / max(1, sum(confusion[i])), 2)
                            for i, c in enumerate(predictor.classes)},
        confusion_matrix=confusion,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Оцінка моделі на тестовому наборі")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--backend", default=BACKEND)
    args = parser.parse_args()
    predictor = load_predictor(args.model, args.backend, TORCH_THREADS)
    result = evaluate(predictor, args.data_dir / "speech_commands")
    result.update(model_version=predictor.version, backend=predictor.backend, host=os.uname().nodename)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
