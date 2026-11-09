"""Вимірювання latency сервісу: N запитів до /predict після W «розігрівних».

python scripts/benchmark.py --url http://localhost:8000 -n 200 --warmup 10 [--out results/x.json]
"""
import argparse
import json
import statistics
import time
from pathlib import Path

import requests

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


def stats(values: list[float]) -> dict[str, float]:
    s = sorted(values)
    return dict(mean=round(statistics.fmean(s), 3), p50=round(s[len(s) // 2], 3),
                p95=round(s[int(0.95 * (len(s) - 1))], 3), max=round(s[-1], 3))


def run(url: str, n: int, warmup: int) -> dict:
    payloads = [(p.name, p.read_bytes()) for p in sorted(SAMPLES_DIR.glob("*.wav"))]
    session = requests.Session()

    def call(i: int) -> tuple[float, float]:
        name, data = payloads[i % len(payloads)]
        start = time.perf_counter()
        r = session.post(f"{url}/predict", files={"file": (name, data, "audio/wav")}, timeout=10)
        client_ms = (time.perf_counter() - start) * 1000
        r.raise_for_status()
        return r.json()["latency_ms"], client_ms

    for i in range(warmup):
        call(i)
    server, client = zip(*(call(i) for i in range(n)))
    return dict(requests=n, warmup=warmup, server_latency_ms=stats(list(server)), client_latency_ms=stats(list(client)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("-n", "--n", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = run(args.url, args.n, args.warmup)
    print(json.dumps(result, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
