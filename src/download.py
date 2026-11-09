"""Завантаження Google Speech Commands v0.02 (лише обрані класи).

Винесено в окремий модуль, щоб у Dockerfile шар із датасетом кешувався
незалежно від змін коду навчання.
"""
import argparse
import tarfile
import urllib.request
from pathlib import Path

from src.config import DATA_DIR, DATASET_URL, DEFAULT_CLASSES

LISTS = ("validation_list.txt", "testing_list.txt")


def download(data_dir: Path, classes: tuple[str, ...]) -> Path:
    root = data_dir / "speech_commands"
    marker = root / ".complete"
    if marker.exists():
        return root
    root.mkdir(parents=True, exist_ok=True)
    archive = data_dir / "speech_commands_v0.02.tar.gz"
    print(f"Завантаження {DATASET_URL} ...", flush=True)
    urllib.request.urlretrieve(DATASET_URL, archive)

    def wanted(name: str) -> bool:
        name = name.removeprefix("./")
        return name in LISTS or name.split("/", 1)[0] in classes

    print("Розпакування обраних класів ...", flush=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(root, members=[m for m in tar if wanted(m.name)], filter="data")
    archive.unlink()
    marker.touch()
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--classes", nargs="+", default=list(DEFAULT_CLASSES))
    args = parser.parse_args()
    print(download(args.data_dir, tuple(args.classes)))
