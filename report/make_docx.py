import json
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
DATA, FIGS, SHOTS = REPORT / "data", REPORT / "figs", REPORT / "shots"
OUT = REPORT / "Звіт_Лаб3_CI_CD.docx"
REPO_URL = "https://github.com/Aisssaev/integration-lab3"
IMAGE_URL = "ghcr.io/aisssaev/integration-lab3/kws-api"


def load(relative_path):
    return json.loads((DATA / relative_path).read_text())


runs = load("runs.json")
dependabot = load("dependabot.json")
push = {name: load(f"push/{name}.json") for name in ("summary", "metrics", "history", "verify", "latency")}
pull_request = {name: load(f"pull_request/{name}.json") for name in ("summary", "metrics", "history")}
dispatch_summary = load("workflow_dispatch/summary.json")
failed_verify = load("failed/verify.json")
junit = (DATA / "push/junit-threads-1.xml").read_text()
test_names = re.findall(r'name="(test_[a-z_0-9]+)"', junit)
junit_time = float(re.search(r'tests="\d+" time="([\d.]+)"', junit).group(1))

FIGS.mkdir(parents=True, exist_ok=True)
SHOTS.mkdir(parents=True, exist_ok=True)
for stale in ("training_curves.png", "confusion_matrix.png"):
    (FIGS / stale).unlink(missing_ok=True)

classes = push["metrics"]["classes"]
confusion = push["metrics"]["confusion_matrix"]
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
figure_canvas.savefig(FIGS / "confusion_matrix_push.png", dpi=200)
plt.close(figure_canvas)

figure_canvas, axes = plt.subplots(figsize=(6.5, 3.6))
for label, history, marker in (("push у main (10 епох)", push["history"], "o"),
                               ("pull_request (2 епохи)", pull_request["history"], "s")):
    epochs = [entry["epoch"] for entry in history]
    axes.plot(epochs, [100 * entry["val_acc"] for entry in history], marker + "-", label=f"val, {label}")
axes.axhline(85, color="tab:orange", linestyle=":", label="поріг PR, 85 %")
axes.axhline(95, color="red", linestyle="--", label="поріг main, 95 %")
axes.set_xticks(range(1, 11))
axes.set_xlabel("Епоха")
axes.set_ylabel("Validation accuracy, %")
axes.legend(fontsize=8)
axes.grid(alpha=0.3)
figure_canvas.tight_layout()
figure_canvas.savefig(FIGS / "validation_curves.png", dpi=200)
plt.close(figure_canvas)

job_order = ["lint", "gitleaks", "train", "verify", "integration-tests (1)", "integration-tests (2)", "trivy-scan", "build-push"]
figure_canvas, axes = plt.subplots(figsize=(7, 3.8))
positions = range(len(job_order))
bar_width = 0.2
series = (("PR, холодний кеш", "pull_request_cold"), ("PR, теплий кеш", "pull_request"),
          ("main, холодний кеш", "push_cold"), ("main, теплий кеш", "push"))
for offset, (label, key) in enumerate(series):
    values = [(runs[key]["jobs"].get(job, {}).get("duration_s") or 0) / 60 for job in job_order]
    axes.bar([position + (offset - 1.5) * bar_width for position in positions], values, bar_width, label=label)
axes.set_xticks(list(positions), [job.replace("integration-tests ", "tests ") for job in job_order], rotation=30, ha="right")
axes.set_ylabel("Тривалість, хв")
axes.legend(fontsize=8)
axes.grid(axis="y", alpha=0.3)
figure_canvas.tight_layout()
figure_canvas.savefig(FIGS / "job_durations.png", dpi=200)
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


def code_file(path, size=8):
    code(path.read_text(), size)


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


def minutes(seconds):
    return f"{seconds / 60:.1f}"


def job_minutes(run_key, job):
    duration = runs[run_key]["jobs"].get(job, {}).get("duration_s")
    return "—" if duration is None else minutes(duration)


def step_seconds(run_key, job, step):
    return f"{runs[run_key]['jobs'][job]['steps'][step]:.0f}"


for line in ("МІНІСТЕРСТВО ОСВІТИ І НАУКИ УКРАЇНИ", "[Назва університету]", "[Назва кафедри]"):
    para(line, align=WD_ALIGN_PARAGRAPH.CENTER)
for _ in range(6):
    para()
para("ЗВІТ", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=18)
para("з лабораторної роботи №3", align=WD_ALIGN_PARAGRAPH.CENTER)
para("з дисципліни «Інтеграція інформаційних систем»", align=WD_ALIGN_PARAGRAPH.CENTER)
para("на тему: «Автоматизація збірки та розгортання ML-сервісу: CI/CD-пайплайн у GitHub Actions "
     "(навчання в Docker, артефакти, перевірка моделі, публікація образу)»", align=WD_ALIGN_PARAGRAPH.CENTER)
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
    "розібратися, як влаштований GitHub Actions: workflow, подія, job, step, runner, артефакт, секрет;",
    "перетворити базовий CI з ЛР №2 (один job) на багатоетапний пайплайн: lint → навчання → перевірка "
    "моделі → збірка й публікація образу → звіт;",
    "автоматично навчати модель з ЛР №1 у Docker-контейнері та зберігати результати як артефакти: модель, "
    "лог навчання, метрики, звіт;",
    "налаштувати три способи запуску: pull request, push у main і ручний запуск з параметрами;",
    "захистити головну гілку: pull request не можна злити, доки пайплайн не пройшов;",
    "навчитися безпечно працювати із секретами та правами доступу в CI.",
):
    bullet(item)
body("Виконано обов'язкову частину (п. 2.1–2.9) та опціональні завдання 3.1 (кешування), 3.2 (один образ від "
     "перевірки до публікації), 3.3 (інтеграційні тести з matrix) і 3.7 (безпека пайплайна, без підпису "
     "походження образу).")
body(f"Репозиторій: {REPO_URL}. Успішний запуск пайплайна (push у main): {runs['push']['url']}.")

doc.add_heading("1. Модель і датасет", 1)
metrics = push["metrics"]
sizes = metrics["split_sizes"]
body(f"Використано аудіокласифікатор з ЛР №1–2. Датасет – Google Speech Commands v0.02, класи "
     f"{', '.join(classes)}; поділ за офіційними списками: train {sizes['train']}, validation {sizes['val']}, "
     f"test {sizes['test']} записів. Кожен запис приводиться до моно 16 кГц тривалістю 1 с і перетворюється на "
     "лог-Mel-спектрограму 64 × 101, нормалізовану статистиками навчальної вибірки.")
table(["Параметр", "Значення"], [
    ["Архітектура", metrics["architecture"]],
    ["Параметрів", f"{metrics['parameters']:,}".replace(",", " ")],
    ["Розмір model.pt", f"{metrics['model_size_kb']} КБ"],
    ["PyTorch", metrics["torch_version"]],
    ["Навчання", f"{metrics['epochs']} епох, seed {metrics['seed']}, {metrics['train_time_s']:.0f} с у контейнері на runner"],
    ["Accuracy (test)", f"{metrics['accuracy']} %  (best val {metrics['best_val_accuracy']} %)"],
    ["Версія моделі / commit", f"{metrics['model_version']} / {metrics['git_commit'][:7]}"],
], f"Модель, навчена пайплайном (push у main, запуск {runs['push']['id']})", [5, 11])

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
├── report/                         # цей звіт, дані запусків і генератор
├── Dockerfile                      # цілі trainer і runtime
├── .dockerignore                   # білий список контексту збірки
└── requirements-api.txt, requirements-train.txt, requirements-dev.txt""")

doc.add_heading("3. Схема пайплайна", 1)
code(""" pull_request / push / workflow_dispatch
                  │
   lint ──► train ──► verify ──┬──► integration-tests (matrix) ──┐
   gitleaks ─────────────────  ├──► trivy-scan ──────────────────┼──► build-push ──► GHCR
              │          │     │                                 │   (push у main або
              ▼          ▼     ▼                                     ручний запуск з push_image)
           model      report  image (tar, перевірений образ)""", 7)
table(["Job", "needs", "Що робить", "Артефакт / результат"], [
    ["lint", "—", "ruff check src/ scripts/ tests/", "—"],
    ["gitleaks", "—", "пошук секретів в усій історії git (fetch-depth: 0)", "—"],
    ["train", "lint", "збирає ціль trainer, навчає модель через docker run; датасет відновлюється з actions/cache",
     "model: model.pt, labels.json, metrics.json, history.json, train.log"],
    ["verify", "train", "збирає ціль runtime з моделлю з артефакту, запускає сервіс, перевіряє еталонні "
                        "зразки, quality gate, latency, формує звіт; зберігає образ через docker save",
     "report: verify.json, latency.json, model-info.json, report.md, summary.json, service.log; image: kws-api.tar.gz; output image_id"],
    ["integration-tests", "verify", "pytest проти перевіреного образу, matrix TORCH_THREADS = 1 / 2", "junit-threads-1, junit-threads-2"],
    ["trivy-scan", "verify", "сканування перевіреного образу; падіння на CRITICAL з доступним виправленням", "trivy"],
    ["build-push", "verify, integration-tests, trivy-scan, gitleaks",
     "публікує той самий образ, що пройшов перевірку, і доводить збіг ID після pull з реєстру",
     f"{IMAGE_URL}:sha-<commit>, :latest"],
], "Jobs пайплайна та передача даних між ними", [2.6, 2.6, 6, 4.8], size=9)
body("Кожен job виконується на новій чистій машині, тому дані між jobs передаються явно: модель – артефактом "
     "model з train у verify, перевірений образ – артефактом image (docker save) у integration-tests, "
     "trivy-scan і build-push, а ID образу – через outputs job verify. Порядок задає needs: якщо job "
     "упав, усі залежні jobs пропускаються.")

doc.add_heading("3.1. Тригери і пороги accuracy", 2)
table(["Подія", "Епох", "Поріг accuracy", "Публікація образу"], [
    ["pull_request у main", "2", "85 %", "ні"],
    ["push у main", "10", "95 %", "так"],
    ["workflow_dispatch", "з форми (1–50)", "95 %", "якщо push_image = true"],
], "Тригери і параметри", [4.5, 3, 3.5, 5])
body(f"Обґрунтування порогів. Для 4 збалансованих класів випадкове вгадування дає 25 %. Після 2 епох модель "
     f"стабільно показує {pull_request['summary']['accuracy']} % (два незалежні запуски PR дали однаковий "
     "результат завдяки фіксованому seed), тому поріг 85 % для pull request має запас близько 8 в.п. і не "
     "дає хибних падінь, але зупиняє зламаний препроцесинг, переплутані мітки чи несумісні залежності: "
     "у таких випадках accuracy падає до рівня випадкового вгадування. Після 10 епох модель досягає "
     f"{push['summary']['accuracy']} %, тому для main, де образ публікується, поріг піднято до 95 %. "
     "Значення з прикладу в завданні (60 / 80 %) для цієї моделі занадто низькі: вони пропустили б "
     "модель, що помітно гірша за отриману в ЛР №1.")
body("Параметр epochs у ручному запуску перевіряється (ціле число від 1 до 50) до того, як потрапить у "
     "команду. concurrency з cancel-in-progress скасовує застарілі запуски тієї самої гілки. Наслідок: ручний "
     "запуск з main, стартований під час push-запуску в main, скасував би його, тому ручний запуск виконано "
     "після завершення push-запуску.")

doc.add_heading("4. Dockerfile", 1)
code_file(ROOT / "Dockerfile")
body("Зміни порівняно з ЛР №2. У ЛР №2 модель навчалася під час docker build, тому дістати її з образу "
     "було незручно, а датасет потрапляв у шари проміжного етапу. Тепер Dockerfile має дві цілі. Ціль "
     "trainer містить залежності для навчання і код, а саме навчання виконується під час docker run: "
     "датасет монтується з кешу actions/cache у /data, модель записується в змонтований /artifacts і далі "
     "передається між jobs як артефакт. Ціль runtime містить лише залежності інференсу, код і три файли "
     "моделі з artifacts/, працює від непривілейованого користувача appuser (uid 10001), має HEALTHCHECK і "
     "OCI-мітки з версією моделі та commit.")
body("Навчання через docker run, а не docker build, дає три переваги: модель – звичайний файл, який можна "
     "зберегти артефактом і перевірити окремо від образу; кеш шарів Docker (type=gha) не інвалідується "
     "через навчання; датасет не потрапляє в жоден шар. .dockerignore працює як білий список: у контекст "
     "збірки потрапляють лише src/, requirements і три файли моделі, а artifacts/ лишається в .gitignore.")
code_file(ROOT / ".dockerignore")

doc.add_heading("5. Workflow ml-pipeline.yml", 1)
code_file(ROOT / ".github/workflows/ml-pipeline.yml", 7)
for item in (
    "lint – ruff перевіряє код до навчання: синтаксична помилка зупиняє пайплайн за секунди.",
    "gitleaks – сканує всю історію git на випадково закомічені токени й ключі.",
    "train – перевіряє параметр epochs, відновлює датасет з кешу, збирає ціль trainer з кешем шарів і "
    "навчає модель у контейнері. set -o pipefail гарантує, що помилка навчання не буде прихована командою "
    "tee. Лог і модель завантажуються як артефакт навіть після падіння (if: always()).",
    "verify – завантажує модель, збирає runtime-образ, запускає сервіс і чекає /health, перевіряє 8 еталонних "
    "зразків, порівнює accuracy з /model-info з порогом, вимірює latency, пише звіт у Job Summary і "
    "артефакт report, зберігає перевірений образ.",
    "integration-tests – запускає 13 тестів pytest проти перевіреного образу у двох конфігураціях.",
    "trivy-scan – сканує перевірений образ на вразливості.",
    "build-push – публікує перевірений образ у GHCR і доводить, що опубліковано саме його.",
):
    bullet(item)

doc.add_heading("6. Результати запусків", 1)
table(["Тригер", "Епох", "Accuracy, %", "Latency mean / p95, мс", "Розмір моделі, КБ",
       "Тривалість пайплайна, хв", "Образ опубліковано"], [
    ["pull_request", pull_request["summary"]["epochs"], pull_request["summary"]["accuracy"],
     f"{load('pull_request/summary.json')['latency_ms']['mean']} / {load('pull_request/summary.json')['latency_ms']['p95']}",
     pull_request["summary"]["model_size_kb"], minutes(runs["pull_request"]["duration_s"]), "ні (build-push пропущено)"],
    ["push у main", push["summary"]["epochs"], push["summary"]["accuracy"],
     f"{push['summary']['latency_ms']['mean']} / {push['summary']['latency_ms']['p95']}",
     push["summary"]["model_size_kb"], minutes(runs["push"]["duration_s"]), f"так, sha-{runs['push']['sha']}, latest"],
    ["workflow_dispatch (epochs = 5, push_image = true)", dispatch_summary["epochs"], dispatch_summary["accuracy"],
     f"{dispatch_summary['latency_ms']['mean']} / {dispatch_summary['latency_ms']['p95']}",
     dispatch_summary["model_size_kb"], minutes(runs["workflow_dispatch"]["duration_s"]), f"так, sha-{runs['workflow_dispatch']['sha']}, latest"],
], "Результати пайплайна (п. 2.9), запуски з теплим кешем", [3.4, 1.2, 1.8, 2.4, 1.8, 2.2, 3.2], size=9)
body("Latency – серверна (поле latency_ms), 100 запитів після 10 розігрівних на runner GitHub (2 vCPU). "
     "Розмір моделі не залежить від кількості епох: змінюються лише значення ваг. Різниця latency між "
     "запусками (1.5–2.2 мс) – шум спільних віртуальних машин runner, а не властивість моделі.")
table(["Тригер", "Гілка", "Запуск", "Результат"], [
    ["pull_request (PR #1, перший запуск)", runs["pull_request_cold"]["branch"], runs["pull_request_cold"]["url"], "success"],
    ["pull_request (PR #8)", runs["pull_request"]["branch"], runs["pull_request"]["url"], "success"],
    ["pull_request (PR #2, зламаний expected.json)", runs["failed"]["branch"], runs["failed"]["url"], "failure на verify"],
    ["push у main (перший запуск)", "main", runs["push_cold"]["url"], "failure на build-push (див. 8.3)"],
    ["push у main", "main", runs["push"]["url"], "success"],
    ["workflow_dispatch", "main", runs["workflow_dispatch"]["url"], "success"],
], "Посилання на запуски", [4.5, 3.3, 6.2, 2.5], size=9)
figure(SHOTS / "run_pull_request.png", "Запуск з pull request: build-push пропущено")
figure(SHOTS / "run_push.png", "Запуск з push у main: усі jobs, включно з build-push")
figure(SHOTS / "run_dispatch_form.png", "Форма ручного запуску з параметрами epochs і push_image")
figure(SHOTS / "run_dispatch.png", "Ручний запуск (epochs = 5, push_image = true)")
figure(SHOTS / "artifacts.png", "Артефакти запуску: model, report, image, junit-threads-1/2, trivy")
figure(SHOTS / "job_summary.png", "Job Summary зі звітом make_report.py")

doc.add_heading("7. Перевірка якості моделі", 1)
doc.add_heading("7.1. Еталонні зразки і quality gate", 2)
body("scripts/verify_model.py надсилає 8 записів із тестового спліту (по 2 на клас, не входять до навчальної "
     "вибірки) на /predict запущеного контейнера і порівнює відповідь з samples/expected.json. Будь-яка "
     "помилка завершує job з кодом 1. Це ловить проблеми, які accuracy, порахована під час навчання, не "
     "покаже: розбіжність препроцесингу між навчанням і сервісом, неправильний порядок класів у labels.json, "
     "некоректне завантаження ваг. Accuracy для quality gate береться з /model-info запущеного сервісу, тобто "
     "перевіряється саме та модель, яку завантажив образ.")
table(["Зразок", "Очікуваний", "Передбачений", "Впевненість", "Результат"],
      [[result["file"], result["expected"], result["predicted"], f"{result['confidence']:.4f}",
        "OK" if result["ok"] else "FAIL"] for result in push["verify"]["results"]],
      f"Еталонні зразки, push у main: {push['verify']['passed']} / {push['verify']['total']}", [4, 3, 3, 3, 3])
table(["Клас"] + classes, [
    ["2 епохи (PR), %"] + [pull_request["summary"]["per_class_accuracy"][name] for name in classes],
    ["10 епох (main), %"] + [push["summary"]["per_class_accuracy"][name] for name in classes],
], "Accuracy за класами", [4, 3, 3, 3, 3])
figure(FIGS / "validation_curves.png", "Validation accuracy за епохами і пороги quality gate", 15)
figure(FIGS / "confusion_matrix_push.png", "Матриця помилок моделі з main на тестовому наборі", 11)
body("Після 2 епох модель найчастіше плутає no і down: обидва слова короткі й мають схожі дифтонги [oʊ] і "
     "[aʊ]. Після 10 епох accuracy цих класів зростає до 98.0 % (no) і 95.1 % (down).")

doc.add_heading("7.2. Запуск, що впав на verify, і заблокований pull request", 2)
wrong = next(result for result in failed_verify["results"] if not result["ok"])
body(f"Для перевірки захисту створено PR #2, у якому в samples/expected.json для {wrong['file']} свідомо вказано "
     f"клас «{wrong['expected']}». Модель правильно передбачила «{wrong['predicted']}» (впевненість "
     f"{wrong['confidence']}), тому verify_model.py повернув код 1: {failed_verify['passed']} / "
     f"{failed_verify['total']} зразків. Job verify упав, integration-tests, trivy-scan і build-push "
     f"пропущено, а кнопка Merge заблокована правилом захисту гілки. Запуск: {runs['failed']['url']}.")
figure(SHOTS / "run_failed_verify.png", "Запуск, що впав на job verify (Golden-sample check)")
figure(SHOTS / "pr_blocked.png", "Pull request #2: злиття заблоковане, бо required check verify не пройшов")

doc.add_heading("8. Публікація образу", 1)
doc.add_heading("8.1. Один образ від перевірки до публікації (опц. 3.2)", 2)
body("Образ збирається один раз – у job verify. Після перевірки він зберігається через docker save, "
     "передається як артефакт у integration-tests, trivy-scan і build-push, а його ID – через outputs job "
     "verify. build-push завантажує tar, перевіряє, що ID збігається з перевіреним, тегує й публікує образ. "
     "Потім видаляє локальні копії, завантажує образ з GHCR за digest і ще раз порівнює ID.")
table(["Що порівнюється", "Значення"], [
    ["ID образу, перевіреного в verify (outputs.image_id)", "sha256:05f96d86e4d1fda9bc09a476d597117fcac700d24fe5058ad160708d42492727"],
    ["Digest версії пакета в GHCR", "sha256:05f96d86e4d1fda9bc09a476d597117fcac700d24fe5058ad160708d42492727"],
    ["Теги", f"sha-{runs['push']['sha']}, latest"],
], f"Доказ збігу перевіреного й опублікованого образів (запуск {runs['push']['id']})", [7, 9], size=9)
body("На runner використовується сховище образів containerd, де ID образу дорівнює digest маніфесту, тому "
     "ID перевіреного образу й digest у реєстрі збігаються побітово.")
doc.add_heading("8.2. Перевірка опублікованого образу", 2)
code((DATA / "ghcr_check.txt").read_text())
body("Версія моделі й commit у /model-info збігаються з OCI-мітками образу і з тегом sha-<commit>, тому за "
     "тегом однозначно встановлюється, з якого коду і якої моделі зібрано образ. Перевірку виконано на "
     "Apple Silicon: образ linux/amd64 працює через емуляцію, тому latency тут не показова.")
figure(SHOTS / "ghcr_package.png", "Опублікований пакет kws-api у GHCR")
doc.add_heading("8.3. Виявлені проблеми", 2)
body(f"Перший push у main ({runs['push_cold']['url']}) опублікував образ, але впав на кроці «Prove pushed "
     "image is the verified one». Скрипт брав перший елемент RepoDigests, а на runner із containerd це "
     "локальне посилання kws-api@sha256:…, тому docker pull звертався до неіснуючого репозиторію. "
     "Виправлення (PR #8) вибирає digest саме репозиторію GHCR; наступний push пройшов повністю.")
body("Ручний запуск з main з push_image = true публікує образ з тегом sha-<commit> того самого коміту, що "
     "й останній push. Тому він перевісив теги sha-9329155 і latest на образ з моделлю на 5 епох, а образ з "
     "push-запуску (10 епох) залишився в реєстрі лише за digest. Щоб так не було, ручному запуску варто "
     "давати окремий тег (наприклад, з номером запуску) і не оновлювати latest.")
doc.add_heading("8.4. Реєстр чи tar-артефакт", 2)
body("Tar-артефакт використовується лише для передачі образу між jobs одного запуску. Як спосіб доставки він "
     "гірший за реєстр: живе обмежений час (retention-days: 3), займає квоту сховища артефактів (~300 МБ на "
     "запуск), завантажується лише через UI або API з токеном і docker load, а не docker pull; не має тегів, "
     "digest-адресації, пошарової дедуплікації і не підтримується оркестраторами. Реєстр зберігає образ, "
     "доки його не видалено, і віддає лише відсутні шари.")

doc.add_heading("9. Захист гілки main", 1)
body("Правило для main: Require a pull request before merging; Require status checks to pass before merging "
     "з перевірками lint, train і verify; Require branches to be up to date. Тому зміни потрапляють у main "
     "лише через pull request, у якому пайплайн навчив модель і перевірив її якість.")
figure(SHOTS / "branch_protection.png", "Правило захисту гілки main")

doc.add_heading("10. Секрети і права доступу", 1)
for item in (
    "окремих секретів не створено: публікація в GHCR використовує тимчасовий GITHUB_TOKEN;",
    "на рівні workflow GITHUB_TOKEN має лише contents: read; право packages: write видано тільки job build-push;",
    "pull request (у тому числі з форка) не виконує build-push, тому не отримує права на запис у реєстр;",
    "секрети не передаються в образ через ARG, ENV чи COPY: перевірка docker history --no-trunc не знайшла "
    "жодного рядка зі словами token, secret, password чи префіксами токенів GitHub (див. 8.2);",
    "gitleaks перевіряє всю історію git; build-push залежить від нього, тому образ не публікується, якщо в "
    "репозиторії знайдено секрет.",
):
    bullet(item)
figure(SHOTS / "workflow_permissions.png", "Settings → Actions → General → Workflow permissions")

doc.add_heading("11. Опціональні завдання", 1)
doc.add_heading("11.1. Кешування і прискорення (3.1)", 2)
body("Кешуються три речі: датасет (actions/cache, ключ speech-commands-v0.02-yes-no-up-down), шари Docker "
     "для цілей trainer і runtime (cache-from / cache-to type=gha з окремими scope) і пакети pip для "
     "інтеграційних тестів (actions/setup-python з cache: pip). Холодний кеш – перші запуски в репозиторії, "
     "теплий – наступні запуски з тим самим requirements.")
table(["Job / крок", "PR, холодний", "PR, теплий", "main, холодний", "main, теплий"], [
    ["train, хв", job_minutes("pull_request_cold", "train"), job_minutes("pull_request", "train"),
     job_minutes("push_cold", "train"), job_minutes("push", "train")],
    ["  Build trainer image, с", step_seconds("pull_request_cold", "train", "Build trainer image"),
     step_seconds("pull_request", "train", "Build trainer image"),
     step_seconds("push_cold", "train", "Build trainer image"), step_seconds("push", "train", "Build trainer image")],
    ["  Train in container, с", step_seconds("pull_request_cold", "train", "Train in container"),
     step_seconds("pull_request", "train", "Train in container"),
     step_seconds("push_cold", "train", "Train in container"), step_seconds("push", "train", "Train in container")],
    ["verify, хв", job_minutes("pull_request_cold", "verify"), job_minutes("pull_request", "verify"),
     job_minutes("push_cold", "verify"), job_minutes("push", "verify")],
    ["  Build runtime image, с", step_seconds("pull_request_cold", "verify", "Build runtime image"),
     step_seconds("pull_request", "verify", "Build runtime image"),
     step_seconds("push_cold", "verify", "Build runtime image"), step_seconds("push", "verify", "Build runtime image")],
    ["integration-tests (1), хв", job_minutes("pull_request_cold", "integration-tests (1)"),
     job_minutes("pull_request", "integration-tests (1)"), job_minutes("push_cold", "integration-tests (1)"),
     job_minutes("push", "integration-tests (1)")],
    ["trivy-scan, хв", job_minutes("pull_request_cold", "trivy-scan"), job_minutes("pull_request", "trivy-scan"),
     job_minutes("push_cold", "trivy-scan"), job_minutes("push", "trivy-scan")],
    ["build-push, хв", "—", "—", job_minutes("push_cold", "build-push"), job_minutes("push", "build-push")],
    ["Увесь пайплайн, хв", minutes(runs["pull_request_cold"]["duration_s"]), minutes(runs["pull_request"]["duration_s"]),
     minutes(runs["push_cold"]["duration_s"]), minutes(runs["push"]["duration_s"])],
], "Тривалість jobs з холодним і теплим кешем", [5, 2.7, 2.7, 2.8, 2.8], size=10)
figure(FIGS / "job_durations.png", "Тривалість jobs з холодним і теплим кешем")
body("Кеш шарів Docker скорочує збірку trainer-образу в 3.5–5.5 раза, а runtime-образу – у 2–4.5 раза. Кеш датасету "
     "прибирає завантаження архіву ≈2.3 ГБ з серверів TensorFlow усередині кроку навчання. Разом пайплайн для "
     "pull request прискорився з 10.2 до 4.3 хв, для main – з 13.3 до 7.7 хв. Час самого навчання "
     "(train_time_s) від кешу не залежить і коливається між запусками на ±30 % через спільні runner. "
     "Найдовший job – train: для PR він займає близько половини пайплайна, для main – більше половини.")
doc.add_heading("11.2. Інтеграційні тести (3.3)", 2)
body(f"Job integration-tests завантажує перевірений образ і запускає {len(test_names)} тестів pytest проти "
     "контейнера з matrix TORCH_THREADS = 1 і 2 (fail-fast: false). Результат публікується в JUnit XML як "
     f"артефакт і в Job Summary. У push-запуску пройшли {len(test_names)} / {len(test_names)} тестів за "
     f"{junit_time:.1f} с.")
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
], "Інтеграційні тести", [7, 9], size=10)
doc.add_heading("11.3. Безпека пайплайна (3.7)", 2)
for item in (
    "усі сторонні actions закріплені за повним SHA коміту, а образи trivy і gitleaks – за digest;",
    "trivy сканує перевірений образ і завершує job з помилкою на CRITICAL-вразливості з доступним "
    "виправленням; повний звіт HIGH + CRITICAL зберігається артефактом trivy;",
    "gitleaks перевіряє всю історію git на секрети;",
    "Dependabot щотижня пропонує оновлення actions, базового образу і pip-залежностей;",
    "підпис походження образу (actions/attest-build-provenance) не реалізовано.",
):
    bullet(item)
body("Одразу після першого push Dependabot відкрив pull request з оновленнями, і на кожен з них спрацював "
     "пайплайн. Це показує, навіщо потрібні обов'язкові перевірки:")
table(["PR", "Оновлення", "Результат пайплайна"],
      [[f"#{entry['number']}", entry["title"].replace("build(deps): ", "").replace("build(deps-dev): ", ""),
        "впав на " + ", ".join(entry["failed"]) if entry["failed"] else "пройшов"]
       for entry in sorted(dependabot, key=lambda entry: entry["number"])],
      "Pull request від Dependabot", [1.5, 9, 5.5], size=10)
body("numpy 2.5.5 вимагає Python ≥ 3.12, а образ побудовано на python:3.11-slim, тому pip не знайшов "
     "сумісної версії і job train упав на збірці trainer-образу. Захист гілки не дасть злити таке оновлення.")

doc.add_heading("Висновки", 1)
body("Побудовано CI/CD-пайплайн, який для кожної зміни автоматично навчає модель у контейнері, збирає "
     "сервіс, перевіряє його на еталонних зразках і за порогом accuracy, проганяє інтеграційні тести у двох "
     "конфігураціях, сканує образ і історію git, а після push у main публікує образ у GHCR.")
body(f"Запуски за різними тригерами відрізняються обсягом роботи. Pull request навчає модель 2 епохи "
     f"({pull_request['summary']['accuracy']} %, поріг 85 %) і не публікує образ; з теплим кешем пайплайн "
     f"триває {minutes(runs['pull_request']['duration_s'])} хв. Push у main навчає 10 епох "
     f"({push['summary']['accuracy']} %, поріг 95 %) і публікує образ за "
     f"{minutes(runs['push']['duration_s'])} хв. Ручний запуск дає змінити кількість епох (5 епох – "
     f"{dispatch_summary['accuracy']} %) і вирішити, чи публікувати образ.")
body("Найдовший job – train; кешування датасету і шарів Docker скоротило пайплайн для pull request з 10.2 до "
     "4.3 хв, а для main – з 13.3 до 7.7 хв. Публікується той самий образ, що пройшов перевірку: ID "
     "перевіреного образу дорівнює digest у GHCR. Пайплайн зупинив два різні дефекти: свідомо зіпсований "
     "еталонний зразок (job verify) і несумісне оновлення numpy від Dependabot (job train). Захист гілки "
     "не дає злити такі зміни в main.")
body(f"Репозиторій: {REPO_URL}. Успішний запуск: {runs['push']['url']}.")

doc.save(OUT)
print(OUT)
