import argparse
import json
import sys
from pathlib import Path

import requests

TIMEOUT_S = 10


def load_expected(path: Path) -> dict[str, str]:
    expected = json.loads(path.read_text())
    if not isinstance(expected, dict) or not expected:
        raise SystemExit(f"{path}: очікується непорожній об'єкт {{файл: клас}}")
    return expected


def check_sample(session: requests.Session, url: str, path: Path, label: str) -> dict:
    try:
        response = session.post(f"{url}/predict", files={"file": (path.name, path.read_bytes(), "audio/wav")},
                                timeout=TIMEOUT_S)
        response.raise_for_status()
        body = response.json()
    except (OSError, requests.RequestException, ValueError) as exc:
        return dict(file=path.name, expected=label, predicted=None, confidence=None, ok=False, error=str(exc))
    return dict(file=path.name, expected=label, predicted=body["label"], confidence=body["confidence"],
                ok=body["label"] == label)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--expected", type=Path, default=Path("samples/expected.json"))
    parser.add_argument("--out", type=Path, default=Path("metrics/verify.json"))
    args = parser.parse_args()

    expected = load_expected(args.expected)
    session = requests.Session()
    results = [check_sample(session, args.url, args.expected.parent / name, label)
               for name, label in sorted(expected.items())]
    passed = sum(r["ok"] for r in results)
    summary = dict(passed=passed, total=len(results), results=results)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    for r in results:
        print(f"{'OK  ' if r['ok'] else 'FAIL'} {r['file']:<12} expected={r['expected']:<5} "
              f"predicted={r['predicted']} confidence={r['confidence']}")
    print(f"golden samples: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
