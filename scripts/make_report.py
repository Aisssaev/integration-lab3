import argparse
import json
import os
from pathlib import Path

MISSING = "—"


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def fmt(value, suffix: str = "") -> str:
    return MISSING if value is None else f"{value}{suffix}"


def build_summary(model: dict, verify: dict, latency: dict, env: dict) -> dict:
    server = latency.get("server_latency_ms", {})
    return dict(
        commit=env.get("GITHUB_SHA", "local")[:7],
        event=env.get("GITHUB_EVENT_NAME", "local"),
        run_url=run_url(env),
        epochs=model.get("epochs"),
        min_accuracy=float(env["MIN_ACCURACY"]) if env.get("MIN_ACCURACY") else None,
        accuracy=model.get("accuracy"),
        per_class_accuracy=model.get("per_class_accuracy"),
        model_size_kb=model.get("model_size_kb"),
        train_time_s=model.get("train_time_s"),
        latency_ms={k: server.get(k) for k in ("mean", "p50", "p95")} if server else None,
        client_latency_ms=latency.get("client_latency_ms"),
        golden_samples={k: verify.get(k) for k in ("passed", "total")} if verify else None,
    )


def run_url(env: dict) -> str | None:
    if not env.get("GITHUB_RUN_ID"):
        return None
    return f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"


def gate_status(summary: dict) -> str:
    accuracy, threshold = summary["accuracy"], summary["min_accuracy"]
    if accuracy is None or threshold is None:
        return MISSING
    return "✅ пройдено" if accuracy >= threshold else "❌ не пройдено"


def render_markdown(summary: dict, verify: dict) -> str:
    latency = summary["latency_ms"] or {}
    golden = summary["golden_samples"] or {}
    lines = [
        "## ML pipeline report",
        "",
        f"Commit `{summary['commit']}` · event `{summary['event']}` · epochs {fmt(summary['epochs'])}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Accuracy (test), % | {fmt(summary['accuracy'])} |",
        f"| Accuracy threshold, % | {fmt(summary['min_accuracy'])} ({gate_status(summary)}) |",
        f"| Model size, KB | {fmt(summary['model_size_kb'])} |",
        f"| Training time, s | {fmt(summary['train_time_s'])} |",
        f"| Latency mean / p50 / p95, ms | {fmt(latency.get('mean'))} / {fmt(latency.get('p50'))} / "
        f"{fmt(latency.get('p95'))} |",
        f"| Golden samples | {fmt(golden.get('passed'))} / {fmt(golden.get('total'))} |",
    ]
    if summary["per_class_accuracy"]:
        lines += ["", "| Class | Accuracy, % |", "|---|---|"]
        lines += [f"| {cls} | {acc} |" for cls, acc in summary["per_class_accuracy"].items()]
    if verify.get("results"):
        lines += ["", "| Sample | Expected | Predicted | Confidence | |", "|---|---|---|---|---|"]
        lines += [f"| {r['file']} | {r['expected']} | {fmt(r['predicted'])} | {fmt(r['confidence'])} | "
                  f"{'✅' if r['ok'] else '❌'} |" for r in verify["results"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", type=Path, default=Path("metrics"))
    parser.add_argument("--model", type=Path, default=Path("artifacts/metrics.json"))
    parser.add_argument("--out", type=Path, default=Path("metrics/report.md"))
    args = parser.parse_args()

    verify = read_json(args.metrics / "verify.json")
    summary = build_summary(read_json(args.model), verify, read_json(args.metrics / "latency.json"), dict(os.environ))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(summary, verify))
    (args.out.parent / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(args.out.read_text())


if __name__ == "__main__":
    main()
