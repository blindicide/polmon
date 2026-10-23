# polmon

[English](#polmon) · [Русский](#русский)

polmon is a resource-efficient platform for controlled network-security experiments in
explicitly isolated laboratories. Phase I combines shared-process synthetic endpoints (L0),
Linux network namespaces (L1), and a Qt desktop client for Windows and Linux. L2 virtual machines
are an architectural extension, not part of the initial implementation.

Phase I (v0.1.0) provides: a Linux FastAPI backend; a standalone Windows client executable built on
GitHub-hosted runners; declarative YAML topologies; L0 synthetic endpoints with Ethernet, ARP, IPv4,
and ICMP echo; L1 namespace endpoints with built-in services; hybrid L0/L1 communication through
one shared TAP; a closed-action scenario engine; SQLite telemetry with bounded PCAP capture; JSON
and Markdown reports; resource admission control and cancellation; automated cleanup and reset;
reproducible benchmarks with retained raw results. Run the target demonstration (50 L0 + 2 L1, one
controlled experiment, telemetry, report, reset) with `.venv/bin/polmon-demo`; see
[docs/DEMO.md](docs/DEMO.md).

Phase II (v0.2.0) replaces the Tkinter client with a Qt (PySide6) desktop client that runs on
Windows and Linux from one code base — dashboard, topology editor and inspector, deployment with
live resource counters, scenarios and experiments with live progress and cancellation, a filterable
telemetry stream, reports and benchmark jobs — and a CI/CD pipeline that tests, packages, verifies
and releases both platforms. Operator guide: [docs/CLIENT.md](docs/CLIENT.md); real screenshots:
[docs/ui/SCREENSHOTS.md](docs/ui/SCREENSHOTS.md); design: [docs/UI-PLAN.md](docs/UI-PLAN.md).

Phase III (v0.3.0) makes the downloads self-contained. The Windows client starts, monitors and
stops its bundled backend from the **Local backend (L0 only)** preset; no Python install or separate
service is needed. This local Windows path intentionally supports synthetic L0 only: Windows has
no Linux network namespaces, so L1/L2 is refused rather than emulated. Use **Remote Linux backend**
for L1 and hybrid TAP experiments. Releases v0.3.0–v0.4.1 also contained standalone backend
bundles (`polmon-backend-<version>-linux-x64.tar.gz`, `polmon-backend-<version>-windows-x64.exe`);
since v0.6.0 the clients embed their L0 backend instead.

Phase IV (v0.4.0) localizes the desktop client — Russian by default, English switchable at run
time, backend refusals rendered from stable message codes — and redesigns its interface (design
tokens, dark navigation, cards and metric tiles, empty/loading/error states, ≥ 4.5:1 contrast).
Visual system, glossary and before/after screenshots: [docs/UI-GUIDE.md](docs/UI-GUIDE.md).

Phase V (v0.5.0) adds the operator workflow: Topology Studio with persistent named-node and UUID
identity, namespace SSH and VNC console access, an authored scenario library with bounded actions
and assertions, and detailed structured logs with correlation, rotating service output, API
streaming and a localized Logs page. The headless evidence, real privileged gates and known
limitations are recorded in [docs/milestones/v0.5.0.md](docs/milestones/v0.5.0.md) and
[docs/evidence/phase-v/](docs/evidence/phase-v/).

Phase VI (v0.6.0) ships self-contained Debian and RPM client packages, embeds the L0 backend and
SQLite in every client artifact (no sibling backend executable), and adds an authenticated packet
workbench for sending exact Ethernet frames from a deployed node.

## Which download?

The table below describes v0.6.0, the latest published release. v0.5.0 is tagged but has no
GitHub release (its release jobs could not start: GitHub Actions billing block); v0.4.1 is the
last release with standalone backend bundles. Releases carry `SHA256SUMS.txt`
(`sha256sum --check --ignore-missing SHA256SUMS.txt`, or `scripts/verify-release.sh vX.Y.Z`):

| You want | Download | Fidelity | Needs |
|---|---|---|---|
| Try polmon on Windows | `polmon-<version>-windows-x64.exe` (one file) or `…-portable.zip` (unzip; starts faster) | L0 via the embedded local backend; **Remote Linux backend** for L1/hybrid | Nothing. Unsigned: SmartScreen warns on first run |
| The desktop client on Linux | `polmon-<version>-linux-x64.tar.gz`, `polmon-client_<version>_amd64.deb` or `polmon-client-<version>-1.x86_64.rpm` | L0 via the embedded local backend; connects to any backend | glibc 2.35+, Qt's xcb libraries ([BUILD-LINUX.md](BUILD-LINUX.md)) |
| A Linux lab backend (L1, hybrid) | `polmon-<version>-py3-none-any.whl` (+ `packaging/linux/polmon-backend.service` from the source tree) | L0; L1 and hybrid TAP when the host permits | Python 3.12; for L1/hybrid `iproute2`, `setpriv`, `/dev/net/tun`, passwordless `sudo` for `ip` (check with `polmon-diagnostics --lab`) |
| The client from Python | the same wheel with the `gui` extra (`polmon-client`) | Connects to any backend; its local backend is the installed `polmon-backend` | Python 3.12 |

Since v0.1.0 (see [CHANGELOG.md](CHANGELOG.md)): hybrid traffic works in both directions (L1
namespaces can ARP for and ping L0 endpoints), optional bearer-token API authentication that is
mandatory off loopback, in-namespace workloads that never run as root, verified scenario
preconditions, storage admission, `polmon-diagnostics --lab`, GUI tests on Windows and under Xvfb,
and a CI dependency audit. Documentation index: [docs/README.md](docs/README.md).

## Quick start

Source-development requirements: Linux, `/usr/bin/python3.12`, and `uv`. The privileged laboratory (L1/hybrid)
additionally needs `iproute2`, `setpriv`, `/dev/net/tun`, and passwordless `sudo` for `ip`; check
with `.venv/bin/polmon-diagnostics --lab`.

```bash
uv venv --python /usr/bin/python3.12
uv pip install -e '.[dev,gui]'
scripts/check.sh              # lint + rootless tests
.venv/bin/polmon-backend
```

Helper scripts in `scripts/`: `check.sh` (ordinary gate), `privileged-tests.sh` (laboratory tests
with a before/after proof that the host network was untouched), `lab-cleanup.sh` (list or remove
leftover platform-named namespaces and interfaces), `run-benchmarks.sh` (recorded benchmark suite),
and `verify-release.sh` (download a release and check its SHA-256).

Benchmarks run only on explicit request: `.venv/bin/polmon-benchmark l0|l1|target|summarize`. See
[docs/BENCHMARKS.md](docs/BENCHMARKS.md) for limits, method, and the retained raw results.

To control a backend from another machine (for example the desktop client on Windows), start it
with a token:
`POLMON_API_TOKEN=... .venv/bin/polmon-backend --host <lab-host-address>` (or `--api-token-file`),
and enter the same token in the client; see [SECURITY.md](SECURITY.md) and the operator runbook
[docs/OPERATIONS.md](docs/OPERATIONS.md).

Run `.venv/bin/polmon-client` to open the desktop client; the default local preset starts its own
L0-only backend on a free loopback port. `--self-test` checks Qt and the client without opening a
window, while `--local-backend-self-test` proves the owned deploy-to-reset workflow. Packaged clients for
Windows (`.exe`) and Linux (`.tar.gz`; since v0.6.0 also `.deb` and `.rpm`) are attached to
every release; see [BUILD-WINDOWS.md](BUILD-WINDOWS.md) and [BUILD-LINUX.md](BUILD-LINUX.md).

Use `.venv/bin/polmon-diagnostics --json` to inspect the Python version, host capabilities,
network-tool availability, and an allow-listed resource snapshot without exposing environment
variables or credentials. Add `--lab` for a read-only check that this host can run the privileged
laboratory (tools, `/dev/net/tun`, ping's `cap_net_raw`, passwordless `sudo ip`); it exits 1 when
not ready. The backend emits structured JSON startup and shutdown logs.

See [ARCHITECTURE.md](ARCHITECTURE.md), [DEVELOPMENT.md](DEVELOPMENT.md),
[docs/LOGS.md](docs/LOGS.md), and [SECURITY.md](SECURITY.md). No license has been granted; a license file will be added only after
the repository owner makes an explicit licensing decision.

An experimental [optional VM-backed L1 runtime](addons/l1-vm/README.md) provides separate
Linux QEMU/KVM jobs through the API and desktop VM page. Linux client bundles include the
addon and pinned read-only image; Windows requires a remote Linux lab for these jobs.
Real guest boot, networking, clone isolation and cleanup acceptance are NOT RUN here.
See [SECURITY.md](SECURITY.md) for the evidence boundary; the Phase VI handoff describes
the earlier scaffold candidate, not current runtime acceptance.

## Русский

Английская часть этого README остаётся основной для будущих изменений. При расхождениях
сверяйтесь с [английской версией](#polmon).

polmon — экономная по ресурсам платформа для контролируемых экспериментов по сетевой
безопасности в явно изолированных лабораториях. Первая фаза объединяет синтетические конечные
точки в общем процессе (L0), сетевые пространства имён Linux (L1) и настольный клиент на Qt для
Windows и Linux. Виртуальные машины L2 — архитектурное расширение, в начальную реализацию они не
входят.

Фаза I (v0.1.0): бэкенд на FastAPI для Linux; автономный клиент для Windows, собираемый на
GitHub-hosted runners; декларативные топологии в YAML; конечные точки L0 с Ethernet, ARP, IPv4 и
ICMP echo; узлы L1 в пространствах имён со встроенными сервисами; гибридная связь L0/L1 через один
общий TAP; движок сценариев с закрытым набором действий; телеметрия в SQLite с ограниченным
захватом PCAP; отчёты в JSON и Markdown; контроль допуска по ресурсам и отмена; автоматическая
очистка и сброс; воспроизводимые бенчмарки с сохранёнными сырыми результатами. Целевая
демонстрация (50 L0 + 2 L1, один контролируемый эксперимент, телеметрия, отчёт, сброс)
запускается командой `.venv/bin/polmon-demo`; см. [docs/DEMO.md](docs/DEMO.md).

Фаза II (v0.2.0) заменяет клиент на Tkinter настольным клиентом на Qt (PySide6), который работает
в Windows и Linux из одной кодовой базы: обзор, редактор и инспектор топологии, развёртывание со
счётчиками ресурсов в реальном времени, сценарии и эксперименты с ходом выполнения и отменой,
фильтруемый поток телеметрии, отчёты и задания бенчмарков. Конвейер CI/CD тестирует, собирает,
проверяет и выпускает обе платформы. Руководство оператора: [docs/CLIENT.md](docs/CLIENT.md);
настоящие снимки экрана: [docs/ui/SCREENSHOTS.md](docs/ui/SCREENSHOTS.md); проект интерфейса:
[docs/UI-PLAN.md](docs/UI-PLAN.md).

Фаза III (v0.3.0) делает загрузки самодостаточными. Клиент для Windows сам запускает, отслеживает
и останавливает встроенный бэкенд в режиме **Локальный (только L0)**; ни Python, ни отдельная
служба не нужны. Этот локальный путь в Windows намеренно поддерживает только синтетический L0: в
Windows нет сетевых пространств имён Linux, поэтому L1/L2 отклоняются, а не эмулируются. Для L1 и
гибридных экспериментов через TAP выберите режим **Удалённый Linux**. Выпуски v0.3.0–v0.4.1
содержали также отдельные сборки бэкенда (`polmon-backend-<version>-linux-x64.tar.gz`,
`polmon-backend-<version>-windows-x64.exe`); начиная с v0.6.0 клиенты встраивают бэкенд L0 в
себя.

Фаза IV (v0.4.0) локализует настольный клиент (по умолчанию русский язык, английский
переключается на ходу, отказы бэкенда отображаются по стабильным кодам сообщений) и обновляет его
интерфейс: токены дизайна, тёмная навигация, карточки и плитки метрик, состояния «пусто»,
«загрузка» и «ошибка», контраст не ниже 4,5:1. Визуальная система, глоссарий и снимки «до/после»:
[docs/UI-GUIDE.md](docs/UI-GUIDE.md).

Фаза V (v0.5.0) добавляет рабочий процесс оператора: Topology Studio с постоянными именами узлов
и идентификаторами UUID, консольный доступ к пространствам имён по SSH и VNC, библиотеку
авторских сценариев с ограниченными действиями и проверками, подробные структурированные журналы
с корреляцией, ротацией вывода сервисов, потоковой выдачей через API и локализованной страницей
журналов. Свидетельства без графического режима, настоящие привилегированные проверки и
известные ограничения записаны в [docs/milestones/v0.5.0.md](docs/milestones/v0.5.0.md) и
[docs/evidence/phase-v/](docs/evidence/phase-v/).

Фаза VI (v0.6.0) выпускает самодостаточные пакеты клиента для Debian и RPM, встраивает бэкенд L0
и SQLite в каждый артефакт клиента (без отдельного исполняемого файла бэкенда) и добавляет
аутентифицированный стенд пакетов (страница «Пакеты») для отправки точных кадров Ethernet
с развёрнутого узла.

### Что скачать?

Таблица описывает v0.6.0 — последний опубликованный выпуск. Тег v0.5.0 существует, но выпуска на
GitHub у него нет (задания выпуска не смогли запуститься из-за блокировки оплаты GitHub Actions);
v0.4.1 — последний выпуск с отдельными сборками бэкенда. К выпускам приложен `SHA256SUMS.txt`
(`sha256sum --check --ignore-missing SHA256SUMS.txt` или `scripts/verify-release.sh vX.Y.Z`):

| Задача | Файл | Уровень эмуляции | Требования |
|---|---|---|---|
| Попробовать polmon в Windows | `polmon-<version>-windows-x64.exe` (один файл) или `…-portable.zip` (распаковать; запускается быстрее) | L0 через встроенный локальный бэкенд; **Удалённый Linux** для L1 и гибрида | Ничего. Файл не подписан: SmartScreen предупредит при первом запуске |
| Настольный клиент в Linux | `polmon-<version>-linux-x64.tar.gz`, `polmon-client_<version>_amd64.deb` или `polmon-client-<version>-1.x86_64.rpm` | L0 через встроенный локальный бэкенд; подключается к любому бэкенду | glibc 2.35+, библиотеки xcb для Qt ([BUILD-LINUX.md](BUILD-LINUX.md)) |
| Лабораторный бэкенд в Linux (L1, гибрид) | `polmon-<version>-py3-none-any.whl` (+ `packaging/linux/polmon-backend.service` из исходного дерева) | L0; L1 и гибридный TAP, если хост позволяет | Python 3.12; для L1 и гибрида `iproute2`, `setpriv`, `/dev/net/tun`, `sudo` без пароля для `ip` (проверка: `polmon-diagnostics --lab`) |
| Клиент из Python | тот же wheel с дополнением `gui` (`polmon-client`) | Подключается к любому бэкенду; локальный бэкенд — установленный `polmon-backend` | Python 3.12 |

С v0.1.0 (см. [CHANGELOG.md](CHANGELOG.md)) появились: гибридный трафик в обе стороны
(пространства имён L1 разрешают по ARP и пингуют конечные точки L0), необязательная
аутентификация API по токену, обязательная вне loopback, нагрузки внутри пространств имён никогда
не работают от root, проверенные предусловия сценариев, контроль допуска по хранилищу,
`polmon-diagnostics --lab`, тесты интерфейса в Windows и под Xvfb, аудит зависимостей в CI.
Указатель документации (на английском): [docs/README.md](docs/README.md).

### Быстрый старт

Для разработки из исходников нужны Linux, `/usr/bin/python3.12` и `uv`. Привилегированной
лаборатории (L1 и гибрид) дополнительно нужны `iproute2`, `setpriv`, `/dev/net/tun` и `sudo` без
пароля для `ip`; проверка — `.venv/bin/polmon-diagnostics --lab`.

```bash
uv venv --python /usr/bin/python3.12
uv pip install -e '.[dev,gui]'
scripts/check.sh              # линтер + тесты без root
.venv/bin/polmon-backend
```

Вспомогательные скрипты в `scripts/`: `check.sh` (обычная проверка), `privileged-tests.sh`
(лабораторные тесты с доказательством «до/после», что сеть хоста не изменилась), `lab-cleanup.sh`
(показать или удалить оставшиеся пространства имён и интерфейсы с именами платформы),
`run-benchmarks.sh` (записываемый набор бенчмарков) и `verify-release.sh` (скачать выпуск и
проверить его SHA-256).

Бенчмарки запускаются только по явному запросу: `.venv/bin/polmon-benchmark
l0|l1|target|summarize`. Лимиты, методика и сохранённые сырые результаты описаны в
[docs/BENCHMARKS.md](docs/BENCHMARKS.md).

Чтобы управлять бэкендом с другой машины (например, из настольного клиента в Windows), запустите
его с токеном:
`POLMON_API_TOKEN=... .venv/bin/polmon-backend --host <lab-host-address>` (или
`--api-token-file`) и введите тот же токен в клиенте; см. [SECURITY.md](SECURITY.md) и
руководство оператора [docs/OPERATIONS.md](docs/OPERATIONS.md).

Команда `.venv/bin/polmon-client` открывает настольный клиент; локальный режим по умолчанию сам
запускает бэкенд только для L0 на свободном порту loopback. `--self-test` проверяет Qt и клиент
без открытия окна, а `--local-backend-self-test` проверяет полный цикл от развёртывания до сброса
на собственном бэкенде. Собранные клиенты для Windows (`.exe`) и Linux (`.tar.gz`, с v0.6.0 также
`.deb` и `.rpm`) приложены к каждому выпуску; см. [BUILD-WINDOWS.md](BUILD-WINDOWS.md) и
[BUILD-LINUX.md](BUILD-LINUX.md).

`.venv/bin/polmon-diagnostics --json` показывает версию Python, возможности хоста, наличие сетевых
инструментов и снимок ресурсов по списку разрешённых полей, не раскрывая переменные окружения и
учётные данные. Флаг `--lab` добавляет проверку только для чтения, может ли этот хост запускать
привилегированную лабораторию (инструменты, `/dev/net/tun`, `cap_net_raw` у ping, `sudo ip` без
пароля); если нет, команда завершается с кодом 1. Бэкенд пишет структурированные журналы запуска
и остановки в JSON.

См. также [ARCHITECTURE.md](ARCHITECTURE.md), [DEVELOPMENT.md](DEVELOPMENT.md),
[docs/LOGS.md](docs/LOGS.md) и [SECURITY.md](SECURITY.md) (на английском). Лицензия не
предоставлена; файл лицензии появится только после явного решения владельца репозитория.

Экспериментальный [необязательный L1-модуль ВМ](addons/l1-vm/README.md) реализует
отдельные задания QEMU/KVM в Linux через API и страницу клиента. Сборки Linux включают
модуль и закреплённый образ только для чтения; Windows требуется удалённая лаборатория Linux.
Реальный запуск гостя, сеть, изоляция клонов и очистка в этой среде **не проверялись**.
Границы свидетельств описаны в [SECURITY.md](SECURITY.md); передача результатов фазы VI
относится к предыдущему кандидату с каркасом.
