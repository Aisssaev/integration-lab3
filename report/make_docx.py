import json
import os
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

ROOT = Path(sys.argv[1]).resolve()
REPORT = ROOT / "report"
FIGS, SHOTS = REPORT / "figs", REPORT / "shots"
OUT = REPORT / "Звіт_Лаб3_CI_CD.docx"
REPO_URL = os.environ.get("REPO_URL", "https://github.com/Aisssaev/integration-lab3")
CI_SUCCESS_URL = os.environ.get("CI_SUCCESS_URL", "[посилання на успішний запуск CI]")
CI_FAILURE_URL = os.environ.get("CI_FAILURE_URL", "[посилання на запуск CI, що впав на quality gate]")


def load(name: str):
    return json.loads((ROOT / name).read_text())


metrics = load("artifacts/metrics.json")
history = load("artifacts/history.json")
latency = load("metrics/latency.json")
verify = load("metrics/verify.json")
summary = load("metrics/summary.json")
junit = (ROOT / "metrics/junit.xml").read_text()
test_names = re.findall(r'name="(test_[a-z_0-9]+)"', junit)
junit_time = re.search(r'tests="\d+" time="([\d.]+)"', junit).group(1)

FIGS.mkdir(parents=True, exist_ok=True)
SHOTS.mkdir(parents=True, exist_ok=True)

classes = metrics["classes"]
confusion = metrics["confusion_matrix"]
figure_canvas, axes = plt.subplots(figsize=(5, 4.2))
image = axes.imshow(confusion, cmap="Blues")
axes.set_xticks(range(len(classes)), classes)
axes.set_yticks(range(len(classes)), classes)
axes.set_xlabel("Передбачений клас")
axes.set_ylabel("Справжній клас")
peak = max(max(row) for row in confusion)
for row_index, row in enumerate(confusion):
    for column_index, value in enumerate(row):
        axes.text(column_index, row_index, value, ha="center", va="center",
                  color="white" if value > peak / 2 else "black")
figure_canvas.colorbar(image)
figure_canvas.tight_layout()
figure_canvas.savefig(FIGS / "confusion_matrix.png", dpi=200)
plt.close(figure_canvas)

figure_canvas, axes = plt.subplots(figsize=(6, 3.4))
epochs = [entry["epoch"] for entry in history]
axes.plot(epochs, [100 * entry["train_acc"] for entry in history], "o-", label="train accuracy")
axes.plot(epochs, [100 * entry["val_acc"] for entry in history], "s-", label="val accuracy")
axes.axhline(summary["min_accuracy"], color="red", linestyle="--", label=f"поріг PR ({summary['min_accuracy']:.0f} %)")
axes.set_xticks(epochs)
axes.set_xlabel("Епоха")
axes.set_ylabel("Accuracy, %")
axes.legend()
axes.grid(alpha=0.3)
figure_canvas.tight_layout()
figure_canvas.savefig(FIGS / "training_curves.png", dpi=200)
plt.close(figure_canvas)

doc = Document()
for section in doc.sections:
    section.left_margin, section.right_margin, section.top_margin, section.bottom_margin = Cm(3), Cm(1.5), Cm(2), Cm(2)
normal = doc.styles["Normal"]
normal.font.name, normal.font.size = "Times New Roman", Pt(14)
normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
normal.paragraph_format.space_after = Pt(4)
for name, size in (("Heading 1", 16), ("Heading 2", 14)):
    heading = doc.styles[name]
    heading.font.name, heading.font.size, heading.font.color.rgb = "Times New Roman", Pt(size), None
    heading.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")

counters = {"fig": 0, "tab": 0}


def para(text="", bold=False, italic=False, align=None, size=None):
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(text)
    run.bold, run.italic = bold, italic
    if size:
        run.font.size = Pt(size)
    if align is not None:
        paragraph.alignment = align
    return paragraph


def body(text):
    paragraph = para(text)
    paragraph.paragraph_format.first_line_indent = Cm(1.25)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY


def bullet(text):
    doc.add_paragraph(text, style="List Bullet")


def code(text, size=9):
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(text.rstrip())
    run.font.name, run.font.size = "Courier New", Pt(size)
    run.element.rPr.rFonts.set(qn("w:eastAsia"), "Courier New")
    paragraph.paragraph_format.left_indent = Cm(0.3)
    paragraph.paragraph_format.space_after = Pt(6)


def code_file(relative_path, size=8):
    code((ROOT / relative_path).read_text(), size)


def figure(path: Path, caption: str, width=16.0):
    counters["fig"] += 1
    if path.exists():
        doc.add_picture(str(path), width=Cm(width))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    else:
        para(f"[Вставте рисунок: {path.name}]", italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(f"Рисунок {counters['fig']} – {caption}", align=WD_ALIGN_PARAGRAPH.CENTER, size=12)


def table(header, rows, caption, widths=None, size=11):
    counters["tab"] += 1
    para(f"Таблиця {counters['tab']} – {caption}", size=12)
    grid = doc.add_table(rows=1, cols=len(header))
    grid.style, grid.alignment = "Table Grid", WD_TABLE_ALIGNMENT.CENTER
    for cell, text in zip(grid.rows[0].cells, header):
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(text))
        run.bold, run.font.size = True, Pt(size)
    for row in rows:
        for cell, value in zip(grid.add_row().cells, row):
            cell.text = ""
            cell.paragraphs[0].add_run(str(value)).font.size = Pt(size)
    if widths:
        for row in grid.rows:
            for cell, width in zip(row.cells, widths):
                cell.width = Cm(width)
    para()


def page_break():
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


for line in ("МІНІСТЕРСТВО ОСВІТИ І НАУКИ УКРАЇНИ", "[Назва університету]", "[Назва кафедри]"):
    para(line, align=WD_ALIGN_PARAGRAPH.CENTER)
for _ in range(6):
    para()
para("ЗВІТ", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=18)
para("з лабораторної роботи №3", align=WD_ALIGN_PARAGRAPH.CENTER)
para("з дисципліни «Інтеграція інформаційних систем»", align=WD_ALIGN_PARAGRAPH.CENTER)
para("на тему: «CI/CD-пайплайн ML-сервісу в GitHub Actions: автоматичне навчання, перевірка якості "
     "та публікація Docker-образу»", align=WD_ALIGN_PARAGRAPH.CENTER)
for _ in range(6):
    para()
para("Виконав: студент групи [Група]", align=WD_ALIGN_PARAGRAPH.RIGHT)
para("[Прізвище Ім'я По батькові]", align=WD_ALIGN_PARAGRAPH.RIGHT)
para("Перевірив: [Посада, ПІБ викладача]", align=WD_ALIGN_PARAGRAPH.RIGHT)
for _ in range(5):
    para()
para("[Місто] – 2026", align=WD_ALIGN_PARAGRAPH.CENTER)
page_break()

doc.add_heading("Мета роботи", 1)
for item in (
    "автоматизувати повний життєвий цикл ML-сервісу з ЛР №1–2 (аудіокласифікатор Google Speech Commands): "
    "навчання, перевірку якості, тестування, сканування безпеки й публікацію образу;",
    "побудувати багатоетапний CI/CD-пайплайн у GitHub Actions із залежностями між job, передачею артефактів "
    "і matrix-стратегією;",
    "впровадити quality gate: пайплайн не пропускає модель з accuracy нижчою за поріг або з помилками на "
    "еталонних зразках;",
    "гарантувати, що в реєстр GHCR публікується той самий образ, що пройшов перевірку, і довести це "
    "порівнянням ідентифікаторів образу;",
    "застосувати практики безпеки ланцюга постачання: закріплення actions за SHA, мінімальні права "
    "GITHUB_TOKEN, пошук секретів (gitleaks), сканування образу (trivy), Dependabot.",
):
    bullet(item)
body(f"Репозиторій: {REPO_URL}.")

doc.add_heading("1. Модель і датасет", 1)
sizes = metrics["split_sizes"]
body(f"Використано модель з ЛР №1–2 без змін в архітектурі. Датасет – Google Speech Commands v0.02, класи "
     f"{', '.join(classes)}; поділ за офіційними списками: train {sizes['train']}, validation {sizes['val']}, "
     f"test {sizes['test']} записів. Кожен запис приводиться до моно 16 кГц тривалістю 1 с і перетворюється на "
     "лог-Mel-спектрограму 64 × 101, нормалізовану статистиками навчальної вибірки.")
table(["Параметр", "Значення"], [
    ["Архітектура", metrics["architecture"]],
    ["Параметрів", f"{metrics['parameters']:,}".replace(",", " ")],
    ["Розмір model.pt / model.onnx", f"{metrics['model_size_kb']} КБ / {metrics['onnx_size_kb']} КБ"],
    ["PyTorch", metrics["torch_version"]],
    ["Навчання", f"{metrics['epochs']} епохи (режим pull_request), seed {metrics['seed']}, "
                 f"{metrics['train_time_s']:.0f} с у контейнері"],
    ["Accuracy (test)", f"{metrics['accuracy']} %  (best val {metrics['best_val_accuracy']} %)"],
    ["Версія моделі", metrics["model_version"]],
], "Модель (прогін пайплайна з 2 епохами)", [5, 11])

doc.add_heading("2. Структура проєкту", 1)
code("""integration-lab3/
├── .github/
│   ├── workflows/ml-pipeline.yml   # CI/CD-пайплайн
│   └── dependabot.yml              # оновлення actions, базового образу, pip
├── src/                            # код з ЛР №2 (data, model, train, api)
├── scripts/
│   ├── verify_model.py             # еталонні зразки → verify.json, exit 1 при помилці
│   ├── benchmark.py                # latency mean / p50 / p95 → latency.json
│   ├── make_report.py              # report.md (Job Summary) + summary.json
│   └── ci_local.sh                 # ті самі кроки локально
├── samples/*.wav, expected.json    # 8 зразків з тестового спліту та очікувані класи
├── tests/                          # інтеграційні тести pytest
├── Dockerfile                      # етапи trainer і runtime
├── .dockerignore                   # білий список контексту збірки
└── requirements-api.txt, requirements-train.txt, requirements-dev.txt""")

doc.add_heading("3. Архітектура пайплайна", 1)
code(""" pull_request / push / workflow_dispatch
                  │
   lint ──► train ──► verify ──┬──► integration-tests (matrix) ──┐
   gitleaks ─────────────────  ├──► trivy-scan ──────────────────┼──► build-push ──► GHCR
              │          │     │                                 │   (push у main або
              ▼          ▼     ▼                                     ручний запуск з push_image)
           model      report  image (tar, перевірений образ)""", 7)
table(["Job", "Що робить", "Артефакт"], [
    ["lint", "ruff check src/ scripts/ tests/", "—"],
    ["gitleaks", "пошук секретів в усій історії git (fetch-depth: 0)", "—"],
    ["train", "збирає етап trainer, навчає модель через docker run; датасет відновлюється з actions/cache",
     "model: model.pt, labels.json, metrics.json, history.json, train.log"],
    ["verify", "збирає етап runtime з моделлю з артефакту, запускає сервіс, перевіряє еталонні зразки, "
               "quality gate за accuracy, вимірює latency, формує звіт",
     "report: verify.json, latency.json, model-info.json, report.md, summary.json, service.log; image"],
    ["integration-tests", "pytest проти перевіреного образу, matrix TORCH_THREADS = 1 / 2", "junit-threads-*"],
    ["trivy-scan", "сканування образу; падіння на CRITICAL з доступним виправленням", "trivy"],
    ["build-push", "публікує той самий образ, що пройшов перевірку, і доводить збіг ID після pull з реєстру",
     "ghcr.io/<owner>/<repo>/kws-api:sha-<commit>, :latest"],
], "Jobs пайплайна", [3, 8, 5], size=10)
table(["Подія", "Епох", "Поріг accuracy", "Публікація образу"], [
    ["pull_request у main", "2", "85 %", "ні"],
    ["push у main", "10", "95 %", "так"],
    ["workflow_dispatch", "з форми (1–50)", "95 %", "якщо push_image = true"],
], "Тригери і параметри", [4.5, 3, 3.5, 5])
body("Для pull request модель навчається лише 2 епохи: цього достатньо, щоб виявити зламаний препроцесинг, "
     "переплутані мітки чи несумісність залежностей, і зворотний зв'язок приходить за кілька хвилин. Повне "
     "навчання на 10 епох і жорсткіший поріг 95 % застосовуються тільки до коду, що потрапляє в main і "
     "публікується. Параметр epochs у ручному запуску перевіряється (ціле число від 1 до 50) до того, як він "
     "потрапить у команду. concurrency з cancel-in-progress скасовує застарілі запуски тієї самої гілки.")

doc.add_heading("4. Dockerfile", 1)
code_file("Dockerfile")
body("Етап trainer містить залежності для навчання та код. Навчання виконується під час docker run, а не "
     "docker build: датасет (≈500 МБ) монтується з кешу actions/cache у /data, а модель записується в "
     "змонтований /artifacts і далі передається між job як артефакт. Так кеш шарів Docker (type=gha) не "
     "інвалідується через датасет, а модель не потрапляє в проміжні шари.")
body("Етап runtime містить лише залежності інференсу, код і три файли моделі. Сервіс працює від "
     "непривілейованого користувача appuser (uid 10001), має HEALTHCHECK та OCI-мітки з версією моделі й "
     "commit. .dockerignore працює як білий список: у контекст збірки потрапляють тільки src/, requirements "
     "і три файли з artifacts/.")
code_file(".dockerignore")

doc.add_heading("5. Workflow", 1)
code_file(".github/workflows/ml-pipeline.yml", 7)

doc.add_heading("6. Перевірка якості моделі", 1)
doc.add_heading("6.1. Еталонні зразки", 2)
body("scripts/verify_model.py надсилає 8 записів із тестового спліту (по 2 на клас) на /predict запущеного "
     "контейнера і порівнює відповідь з samples/expected.json. Будь-яка помилка завершує job з кодом 1. Це "
     "ловить проблеми, які accuracy на тестовому наборі не покаже: розбіжність препроцесингу між навчанням "
     "і сервісом, неправильний порядок класів у labels.json, некоректне завантаження ваг.")
table(["Зразок", "Очікуваний", "Передбачений", "Впевненість", "Результат"],
      [[result["file"], result["expected"], result["predicted"], f"{result['confidence']:.4f}",
        "OK" if result["ok"] else "FAIL"] for result in verify["results"]],
      f"Еталонні зразки: {verify['passed']} / {verify['total']}", [4, 3, 3, 3, 3])
doc.add_heading("6.2. Quality gate", 2)
body("Accuracy береться з /model-info запущеного сервісу, а не з файлу на диску. Так перевіряється саме та "
     "модель, яку завантажив образ. Порівняння виконує jq -e; якщо умова хибна, job завершується з "
     "повідомленням ::error::, яке GitHub показує в анотаціях запуску.")
table(["Метрика", "Значення"], [
    ["Accuracy (test), %", f"{summary['accuracy']}"],
    ["Поріг accuracy, %", f"{summary['min_accuracy']} (пройдено)"],
    ["Розмір моделі, КБ", f"{summary['model_size_kb']}"],
    ["Час навчання, с", f"{summary['train_time_s']}"],
    ["Latency сервера mean / p50 / p95 / max, мс",
     " / ".join(str(latency["server_latency_ms"][key]) for key in ("mean", "p50", "p95", "max"))],
    ["Latency клієнта mean / p50 / p95 / max, мс",
     " / ".join(str(latency["client_latency_ms"][key]) for key in ("mean", "p50", "p95", "max"))],
    ["Еталонні зразки", f"{verify['passed']} / {verify['total']}"],
], f"Звіт verify (scripts/make_report.py, {latency['requests']} запитів після {latency['warmup']} розігрівних)",
      [8, 8])
table(["Клас"] + classes, [["Accuracy, %"] + [metrics["per_class_accuracy"][name] for name in classes]],
      "Accuracy за класами", [4, 3, 3, 3, 3])
figure(FIGS / "training_curves.png", "Криві навчання (2 епохи, режим pull_request)", 14)
figure(FIGS / "confusion_matrix.png", "Матриця помилок на тестовому наборі", 11)
body("Найчастіше модель плутає no і down (33 записи no розпізнано як down і 22 записи down як no): "
     "обидва слова короткі й мають схожі дифтонги [oʊ] і [aʊ]. Після 2 епох модель проходить поріг 85 % "
     "для pull request, а для порогу 95 % у main пайплайн навчає її 10 епох.")
figure(SHOTS / "job_summary.png", "Job Summary запуску: звіт make_report.py у GitHub Actions")

doc.add_heading("7. Інтеграційні тести", 1)
body(f"Job integration-tests завантажує збережений перевірений образ (а не збирає новий) і запускає "
     f"{len(test_names)} тестів pytest проти контейнера. Matrix-стратегія проганяє їх з TORCH_THREADS = 1 і 2: "
     "так перевіряється, що сервіс коректно працює і з одним потоком, і з кількома, а fail-fast: false "
     "показує результат обох варіантів навіть якщо один упав. Результат публікується в JUnit XML і в Job Summary.")
table(["Тест", "Що перевіряє"], [
    ["test_health", "/health відповідає 200 і {\"status\": \"ok\"}"],
    ["test_model_info_schema", "схема /model-info: версія, класи, accuracy"],
    ["test_predict_schema", "схема відповіді /predict"],
    ["test_probabilities_distribution", "сума ймовірностей ≈ 1, confidence = максимальна ймовірність"],
    ["test_samples_predicted_correctly", "щонайменше 75 % еталонних зразків класифіковано правильно"],
    ["test_version_consistent", "версія моделі в /predict і /model-info збігається"],
    ["test_spectrogram_shape", "форма вхідної спектрограми 64 × 101"],
    ["test_other_sample_rate_and_stereo", "ресемплінг і зведення стерео до моно"],
    ["test_invalid_file_returns_400", "некоректний файл → 400"],
    ["test_too_long_audio_returns_400", "запис довжиною 12 с → 400"],
    ["test_oversized_and_missing_file", "файл 1.1 МБ → 413, відсутнє поле file → 422"],
    ["test_concurrent_requests", "32 запити у 8 потоків: усі 200, однакова мітка"],
    ["test_latency_p95_within_limit", "p95 і середня latency з 40 запитів < 50 мс"],
], f"Інтеграційні тести: {len(test_names)} / {len(test_names)} пройдено за {junit_time} с", [7, 9], size=10)

doc.add_heading("8. Безпека ланцюга постачання", 1)
for item in (
    "усі сторонні actions закріплені за повним SHA коміту (тег у коментарі), а образи trivy і gitleaks – "
    "за digest: зміна тегу в чужому репозиторії не змінить код, що виконується в пайплайні;",
    "на рівні workflow GITHUB_TOKEN має лише contents: read; право packages: write видано тільки job "
    "build-push. Окремих секретів немає: вхід у GHCR виконується через GITHUB_TOKEN;",
    "gitleaks сканує всю історію git на секрети; build-push залежить від нього, тому образ не публікується, "
    "якщо в репозиторії знайдено секрет;",
    "trivy сканує саме перевірений образ і завершує job з помилкою, якщо є CRITICAL-вразливість з доступним "
    "виправленням; повний звіт HIGH+CRITICAL зберігається як артефакт;",
    "Dependabot щотижня пропонує оновлення actions, базового образу python:3.11-slim і pip-залежностей;",
    "у Dockerfile apt-get upgrade підтягує виправлення безпеки базового образу, сервіс працює не від root.",
):
    bullet(item)

doc.add_heading("9. Публікація перевіреного образу", 1)
body("Образ збирається один раз – у job verify. Після перевірки він зберігається через docker save, "
     "передається як артефакт у integration-tests, trivy-scan і build-push, а його ID передається через "
     "outputs job verify. build-push завантажує tar, перевіряє, що ID збігається з перевіреним, тегує й "
     "публікує образ у GHCR. Потім видаляє локальні копії, завантажує образ з реєстру за digest і ще раз "
     "порівнює ID. Тобто доведено, що в реєстрі лежить побітово той самий образ, який пройшов усі перевірки, "
     "а не перезібраний.")
body("Теги: sha-<commit> (незмінний, однозначно пов'язує образ з кодом) і latest (лише для гілки за "
     "замовчуванням). Версія моделі 1.0.0+<sha7> записується в labels.json, у мітку образу та у відповідь "
     "/model-info.")
code("""docker pull ghcr.io/<owner>/<repo>/kws-api:latest
docker run -d -p 8000:8000 ghcr.io/<owner>/<repo>/kws-api:latest
curl -X POST -F "file=@samples/yes_1.wav" http://localhost:8000/predict
curl http://localhost:8000/model-info   # git_commit збігається з тегом sha-<commit>""")
figure(SHOTS / "build_push_summary.png", "Job Summary build-push: теги, digest і збіг ID образу")
figure(SHOTS / "ghcr_package.png", "Опублікований пакет kws-api у GHCR")

doc.add_heading("10. Результати запусків", 1)
body(f"Успішний запуск: {CI_SUCCESS_URL}.")
body(f"Запуск, що впав на quality gate: {CI_FAILURE_URL}.")
figure(SHOTS / "ci_success.png", "Граф job успішного запуску ml-pipeline")
figure(SHOTS / "ci_failure.png", "Запуск, що впав на quality gate: build-push не виконується")
figure(SHOTS / "artifacts.png", "Артефакти запуску: model, report, image, junit-threads-*, trivy")
body("Ті самі кроки відтворюються локально скриптом scripts/ci_local.sh (train → verify → integration tests). "
     "Наведені в розділах 1, 6 і 7 метрики отримано саме цим скриптом з EPOCHS=2 і MIN_ACCURACY=85, тобто в "
     "режимі pull_request.")
code_file("scripts/ci_local.sh")

doc.add_heading("11. Захист гілки main", 1)
body("Settings → Branches → правило для main: Require a pull request before merging і Require status checks "
     "to pass (lint, train, verify). Так зміни потрапляють у main лише через pull request, у якому пайплайн "
     "навчив модель, перевірив її якість і прогнав тести.")
figure(SHOTS / "branch_protection.png", "Правило захисту гілки main")

doc.add_heading("Висновки", 1)
body("Побудовано CI/CD-пайплайн, який для кожної зміни автоматично навчає модель у контейнері, збирає "
     "сервіс, перевіряє його на еталонних зразках і за порогом accuracy, проганяє інтеграційні тести у двох "
     "конфігураціях, сканує образ і історію git на вразливості та секрети, а після push у main публікує "
     "образ у GHCR.")
body(f"У режимі pull_request (2 епохи) модель досягає {metrics['accuracy']} % accuracy за "
     f"{metrics['train_time_s']:.0f} с навчання, проходить поріг 85 %, правильно класифікує "
     f"{verify['passed']} з {verify['total']} еталонних зразків; серверна latency p95 – "
     f"{latency['server_latency_ms']['p95']} мс; усі {len(test_names)} інтеграційних тестів пройдено.")
body("Ключова властивість пайплайна – публікується той самий образ, що пройшов перевірку: він збирається "
     "один раз, передається між job як артефакт, а його ID порівнюється до публікації і після завантаження "
     "з реєстру. Розділення порогів для pull request і main дає швидкий зворотний зв'язок під час розробки і "
     "водночас не пропускає в реєстр модель нижчої якості.")

REPORT.mkdir(parents=True, exist_ok=True)
doc.save(OUT)
print(OUT)
