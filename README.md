# Лабораторна №3 — CI/CD-пайплайн ML-сервісу в GitHub Actions

Аудіокласифікатор з ЛР №1–2 (Google Speech Commands: yes / no / up / down, лог-Mel + KeywordCNN у PyTorch)
тепер навчається, перевіряється і публікується автоматично: `.github/workflows/ml-pipeline.yml`.

```
 pull_request / push / workflow_dispatch
                  │
   lint ──► train ──► verify ──┬──► integration-tests (matrix) ──┐
   gitleaks ─────────────────  ├──► trivy-scan ──────────────────┼──► build-push ──► GHCR
              │          │     │                                 │   (push у main або
              ▼          ▼     ▼                                     ручний запуск з push_image)
           model      report  image (tar, перевірений образ)
```

| Job | Що робить | Артефакт |
|---|---|---|
| `lint` | `ruff check src/ scripts/ tests/` | — |
| `gitleaks` | пошук секретів в усій історії git | — |
| `train` | збирає ціль `trainer`, навчає модель через `docker run` (датасет з `actions/cache`) | `model`: model.pt, labels.json, metrics.json, history.json, train.log |
| `verify` | збирає ціль `runtime` з моделлю з артефакту, еталонні зразки, quality gate, latency | `report`: verify.json, latency.json, model-info.json, report.md, summary.json, service.log; `image` |
| `integration-tests` | pytest проти перевіреного образу, matrix `TORCH_THREADS` 1 / 2 | `junit-threads-*` |
| `trivy-scan` | сканування образу, падіння на CRITICAL з доступним виправленням | `trivy` |
| `build-push` | публікує **той самий** образ, що пройшов перевірку, і доводить збіг ID | образ `ghcr.io/<owner>/<repo>/kws-api:sha-<commit>`, `:latest` |

## Тригери

| Подія | Епох | Поріг accuracy | Публікація образу |
|---|---|---|---|
| `pull_request` у `main` | 2 | 85 % | ні |
| `push` у `main` | 10 | 95 % | так |
| `workflow_dispatch` | з форми (1–50) | 95 % | якщо `push_image = true` |

## Локальний запуск тих самих кроків

```bash
docker build --target trainer -t kws-trainer:ci .
mkdir -p artifacts data
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/data:/data" -v "$PWD/artifacts:/artifacts" \
  kws-trainer:ci --classes yes no up down --epochs 2 --seed 42 --out /artifacts | tee artifacts/train.log

docker build --target runtime -t kws-api:ci .
docker run -d --name kws -p 8000:8000 kws-api:ci
python scripts/verify_model.py --url http://localhost:8000 --expected samples/expected.json --out metrics/verify.json
python scripts/benchmark.py --url http://localhost:8000 --n 100 --warmup 10 --out metrics/latency.json
python scripts/make_report.py --metrics metrics/ --model artifacts/metrics.json --out metrics/report.md
```

## Перевірка опублікованого образу

```bash
docker pull ghcr.io/<owner>/<repo>/kws-api:latest
docker run -d -p 8000:8000 ghcr.io/<owner>/<repo>/kws-api:latest
curl -X POST -F "file=@samples/yes_1.wav" http://localhost:8000/predict
curl http://localhost:8000/model-info   # git_commit збігається з тегом sha-<commit>
```

## Dockerfile

- `trainer` — залежності для навчання і код; навчання запускається під час `docker run`, модель пишеться в змонтований `/artifacts`, датасет — у змонтований `/data`.
- `runtime` — лише залежності інференсу, код і три файли моделі з `artifacts/` (`model.pt`, `labels.json`, `metrics.json`).
- `.dockerignore` працює як білий список: у контекст збірки потрапляють лише `src/`, requirements і ці три файли. `artifacts/` при цьому лишається в `.gitignore`.

## Захист гілки `main`

Settings → Branches → rule для `main`: *Require a pull request before merging* і *Require status checks to pass*
(`lint`, `train`, `verify`).

## Секрети

Окремих секретів немає: публікація в GHCR використовує `GITHUB_TOKEN`, право `packages: write` видано лише job
`build-push`, на рівні workflow — `contents: read`.

## Структура

```
.github/workflows/ml-pipeline.yml   пайплайн
.github/dependabot.yml              оновлення actions, базового образу, pip
src/                                код з ЛР №2 (data, model, train, evaluate, inference, api)
scripts/verify_model.py             еталонні зразки -> verify.json, exit 1 при помилці
scripts/benchmark.py                latency mean / p50 / p95 -> JSON
scripts/make_report.py              report.md (Job Summary) + summary.json
samples/*.wav, samples/expected.json  8 зразків з тестового спліту і очікувані класи
tests/                              інтеграційні тести pytest
```
