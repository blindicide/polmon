# Desktop client UI guide

The visual system, the language rules and the evidence for the polmon desktop client
(`polmon-client`). The product UI is Russian by default and English on request; this guide and
all other documentation stay in English. Code: `src/polmon/client/theme.py` (tokens and
stylesheet), `widgets.py` (components), `i18n.py` and `locales/` (catalogs).

## 1. Languages

- **Russian is the default.** English is selectable at run time from *Вид → Язык / View →
  Language* or with **Ctrl+Shift+U**. The switch is immediate: no restart, and nothing else
  changes — connection, open documents, tables, selections, the running operation and the page
  stay as they were. The choice is stored per user; `--language ru|en` or `POLMON_LANGUAGE`
  override it for one run.
- **Every user-visible string comes from a catalog** (`locales/ru.py`, `locales/en.py`, identical
  key sets). Widgets bind to keys (`bind`, `bind_text`, `bind_tip`) and re-render on a switch;
  computed text is built from lazy `Msg` values that render when displayed. Plurals follow CLDR
  (`ru`: one/few/many/other, `en`: one/other).
- **Qt's own strings** (standard dialog buttons, context menus of text fields) come from Qt's
  `qtbase_<lang>.qm`, installed with the language; the packaged clients ship `qtbase_ru.qm`.
- **Backend text is never shown raw.** The backend sends a stable `message_code` and `params`
  with every error (approach (a), [ARCHITECTURE.md](../ARCHITECTURE.md)); the client renders
  `backend.<message_code>`. The English backend `message` appears only, quoted, when an older
  backend sends no code. Tracebacks never reach the UI.
- **What stays as is:** identifiers and data (topology, node and experiment IDs, URLs, file
  paths, YAML and JSON documents, event names), the activity log's history (lines keep the
  language they were written in), and the kept technical terms below.

### Gates

| Gate | What fails it | Where |
|------|---------------|-------|
| `scripts/i18n-lint.py` | a literal handed to a Qt text API, English prose or a composed English f-string in client code, Cyrillic outside the catalogs | CI (both OS), `tests/unit/test_i18n_gates.py` |
| `scripts/i18n-completeness.py` | different key sets or placeholders, wrong plural forms, empty values, English words left in Russian, Cyrillic in English, a glossary variant, a key the code uses but no catalog has (including dynamic families and every backend message code), an unused key | CI (both OS), unit suite |
| Screen walk (`tests/gui/test_language.py`) | English prose on any Russian screen, Cyrillic on any English screen, lost state across a switch, a missing key looked up at run time | GUI suite, run in Russian and in English |

Evidence of both gates passing and failing on injected violations:
[evidence/i18n/](evidence/i18n/). Deliberate exceptions carry an `# i18n: allow` comment;
CLI output, the self-test and the packaged-client probe stay English (they are parsed by CI).

### Glossary

One Russian term per concept. The last column lists variants the completeness gate rejects in
the Russian catalog.

| English | Russian | Concept | Rejected variants |
|---------|---------|---------|-------------------|
| backend | бэкенд | the polmon-backend service the client controls over HTTP | `бекенд`, `бэкэнд`, `сервер\s+polmon` |
| client | клиент | this desktop application | — |
| deployment / deploy | развёртывание / развернуть | a topology instantiated on the backend; the act of creating it | `развертыв`, `деплой` |
| destroy | разобрать | tear one deployment down and release its resources | `уничтож`, `снести` |
| reset environment | сбросить окружение | destroy every deployment the backend owns | — |
| topology | топология | the YAML description of nodes, networks and interfaces | — |
| node | узел | a host in a topology (L0 synthetic or L1 namespace) | `\bнод[аыуе]?\b` |
| endpoint | конечная точка | an addressable interface of a node; the unit of admission limits | `эндпоинт`, `endpoint` |
| namespace | пространство имён | a Linux network namespace backing an L1 node | `неймспейс`, `пространств\w* имен\b` |
| scenario | сценарий | the YAML description of an experiment: actions and conditions | — |
| experiment | эксперимент | one run of a scenario against a deployment | — |
| action | действие | one step of a scenario (probe, request) | — |
| telemetry | телеметрия | the event stream an experiment produces | — |
| report | отчёт | the JSON/Markdown result of an experiment | `\bотчет` |
| benchmark | бенчмарк | a bounded measurement job on the backend | `\bтест производительности` |
| measurement | замер | one row of a benchmark result | — |
| admission control | контроль допуска | the backend check that refuses work beyond its limits | — |
| limit | лимит | a configured ceiling (endpoints, namespaces, memory, duration) | `\bквот` |
| capture | захват | the packet capture (PCAP) of an experiment | `перехват` |
| frame | кадр | one captured Ethernet frame | `фрейм` |
| validate / validation | проверить / проверка | checking a document on the backend without deploying it | `валидац` |
| timeout | тайм-аут | how long the client waits for one HTTP response | `таймаут` |
| activity log | журнал действий | the dockable history of what the client did | `\bлог\b`, `\bлоги\b` |
| CPU | ЦП | processor time and load | `\bCPU\b` |
| emulation level (fidelity) | уровень эмуляции | what the backend can emulate: L0 only, or L0 + L1 + hybrid | — |
| token | токен | the API token the backend requires | — |

**Kept as is** in both languages (names, protocols, formats, units): polmon, L0, L1, L2, TAP,
YAML, JSON, PCAP, CSV, Markdown, HTTP(S), API, URL, IP, IPv4, MAC, ICMP, TCP, ARP, TTL,
Ethernet, EtherType, RSS, ID, SHA-256, Linux, Windows, systemd, sudo, iproute2, ping, veth,
Qt, PySide6, and the unit symbols B, KiB, MiB, GiB, ms, s, min, h (`scripts/i18n_audit.py`,
`KEPT_TERMS`).
Mixed forms are fine where Russian usage has them: *MAC-адрес*, *IP-адрес*,
*loopback-интерфейс*.

**Numbers and units.** Unit symbols are machine notation and are not translated: `B`, `KiB`,
`MiB`, `GiB`, `ms`, `s`, `min`, `h` (`250 ms`, `4.2 s`, `1 min 15 s`, `1 h 05 min`, spin-box
suffixes ` s` and ` MiB`). Decimal point in both languages (values are copied into YAML and
tickets). Timestamps are ISO-like `YYYY-MM-DD HH:MM:SS`.

**Style.** Sentence case for titles, buttons and menu items; buttons are verbs in the
infinitive (*Развернуть*, *Разобрать*, *Сбросить окружение*); Russian quotes «…» around names;
`ё` is always written; no exclamation marks; errors say what happened, then what to do.

## 2. Design tokens

One accent (deep teal) on slate neutrals. Semantic colours are for status only; each has a soft
surface for banners and badges. `theme.TOKENS`:

| Token | Light | Dark | Use |
|-------|-------|------|-----|
| `bg` | `#f2f4f7` | `#0e131a` | window and page background |
| `surface` | `#ffffff` | `#161d26` | cards, inputs, tables |
| `surface_alt` | `#f7f9fb` | `#1b232d` | tiles, alternate rows, table headers |
| `surface_hover` | `#eef2f6` | `#222c38` | hovered rows and buttons |
| `border` | `#dce1e8` | `#2a3542` | card and input borders |
| `border_strong` | `#c3cbd5` | `#3a4757` | editors, focused groups |
| `text` | `#141c26` | `#e6ebf1` | body text and values |
| `text_secondary` | `#3f4b5b` | `#b8c2ce` | field labels, tile captions |
| `text_muted` | `#5a6676` | `#95a1af` | hints, subtitles, secondary lines |
| `accent` | `#0b6680` | `#2d9cbd` | primary buttons, links, selection, charts |
| `accent_hover` | `#08546a` | `#3fb0d2` | primary hover |
| `accent_pressed` | `#064456` | `#2587a4` | primary pressed |
| `accent_soft` | `#d9ecf2` | `#173746` | selected rows, quiet-button hover, pills |
| `accent_text` | `#ffffff` | `#06121a` | text on `accent` |
| `success` | `#146c36` | `#4cc37a` | succeeded, connected, met |
| `warning` | `#8a4f00` | `#e3a33b` | cancelled, not run, modified |
| `danger` | `#b42318` | `#f0736a` | failed, refused, destructive buttons |
| `info` | `#1d5bb8` | `#7aa7f5` | running, connecting |
| `success_soft` | `#e3f3e8` | `#132b1d` | success banner/badge surface |
| `warning_soft` | `#fcf0d8` | `#33260f` | warning banner/badge surface |
| `danger_soft` | `#fce9e7` | `#3a1716` | error banner/badge surface |
| `info_soft` | `#e4ecfa` | `#152540` | information banner/badge surface |
| `nav_bg` | `#16202b` | `#0a0f15` | sidebar |
| `nav_hover` | `#212e3c` | `#16202b` | sidebar hover |
| `nav_active` | `#0b6680` | `#1f7f9c` | current page |
| `nav_text` | `#cdd6e0` | `#c3cdd8` | sidebar items |
| `nav_text_active` | `#ffffff` | `#ffffff` | current page, product name |
| `nav_muted` | `#8f9cab` | `#8593a3` | sidebar section and footer |
| `chart` | `#0b6680` | `#3fb0d2` | sparklines |
| `focus` | `#2b8fb0` | `#3fb0d2` | keyboard-focus ring |

Themes: *system* (follows the OS), *light*, *dark* — **Ctrl+Shift+T** cycles them.

### Scales

| Scale | Steps |
|-------|-------|
| Spacing (`SPACE`, 4-px grid) | `xs` 4 · `sm` 8 · `md` 12 · `lg` 16 · `xl` 24 |
| Type (`TYPE`, px) | caption 11 · body 13 (strong 13/600) · subtitle 15 · title 20 · metric 22 |
| Radius (`RADIUS`) | control 6 · card 8 · pill 10 |
| Control height | 28 px for buttons, inputs, combo and spin boxes |

Page padding is `lg` horizontally and `sm` vertically; cards have `md` padding and `sm` gaps;
tiles show a caption (11/600), one metric (22/600) and one muted detail line.

## 3. Layout and components

- **Window:** dark sidebar (brand, *Рабочее пространство* navigation, connection footer), a
  connection header (mode, URL, token, timeout, connect/disconnect, emulation-level pill,
  state), the page, the dockable activity log and the status bar (connection summary, busy
  indicator or operation progress with *Отменить*, client version).
- **Page:** title and one-line subtitle, header actions on the right, one problem banner, then
  cards. Everything fits 1440×900 in both languages with a banner shown
  (`test_window_fits_1440_by_900_on_every_page_with_banners`).
- **Card** (`Card`): title, optional muted hint, content. **KeyValueGrid**: label/value pairs in
  column pairs, long values in the first column, identifiers monospaced and never broken.
  **ResourceTiles**: live counters with sparklines. **Tables** (`make_table`): sortable,
  resizable, alternating rows, monospaced identifier columns, numbers right-aligned, status
  cells with glyph + word. Columns fit their content (capped at 360 px); when a table is wider
  than its view, header slack is given up first, cell content is never cut, and only then does
  the table scroll.
- **Buttons by role:** *primary* (filled accent, one per area), *secondary* (outlined),
  *danger* (red outline; always confirmed), *quiet* (text only, for links such as *Все отчёты*).
  The primary action of each screen: *Подключиться* (header, while disconnected), *Развернуть…*
  (topologies), *Развернуть* (deployment), *Запустить эксперимент* (scenarios), *Экспорт CSV…*
  (telemetry), *Сохранить Markdown…* (reports), *Запустить бенчмарк* (benchmarks); the
  dashboard is read-only. While connected to the Local backend, *Отключиться* is a danger
  button: it stops the owned backend.
- **States** (`StateView`): *empty* (○ + what to do next), *loading* (spinner + what is
  loading), *error* (✕ + the problem), always with a sentence, never a blank area.
- **Feedback:** problem banners (title — detail, bullet items, hint; closable), a status-bar
  busy indicator for any request that takes longer than 400 ms, operation progress with
  percentage, step, elapsed time, ETA and *Отменить* (Esc), and a task-bar alert when a long
  operation ends while the window is in the background.
- **Destructive actions** (*Разобрать*, *Сбросить окружение*, disconnecting from the Local
  backend — it stops the owned backend —, quitting with an operation
  running) ask for confirmation in a dialog that names the object and the consequence.

## 4. Usability floor

- **Contrast ≥ 4.5:1** for every text/background token pair in both themes, verified by
  `tests/unit/test_theme_contrast.py` (72 pairs).
- **Never colour alone:** each status has its own glyph — ✓ success, ● in progress, ! warning,
  ✕ error, ○ inactive — beside the word, in tables, badges, tiles and the status bar.
- **Keyboard:** every action has a menu entry; tab order follows reading order; the focus ring
  uses `focus`; the shortcut list is in *Справка → Сочетания клавиш* (F1) and in
  [CLIENT.md](CLIENT.md#keyboard-shortcuts).
- **Assistive technology:** every input, editor, list and table has an accessible name from the
  catalog (`a11y.*`), checked by `test_inputs_editors_and_views_have_accessible_names`.

| Keys | Action |
|------|--------|
| Ctrl+Return | connect / disconnect |
| Ctrl+L | focus the backend URL |
| F5 | refresh |
| Ctrl+O / Ctrl+Shift+O | open a topology / a scenario |
| Ctrl+S | save the current document |
| Ctrl+Shift+V | validate |
| Ctrl+D / Ctrl+Shift+D | deploy / destroy |
| Ctrl+Shift+R | reset the environment |
| Ctrl+R | run the experiment |
| Esc | cancel the running operation |
| Ctrl+1 … Ctrl+7 | go to a page |
| Ctrl+Shift+T | cycle the theme |
| Ctrl+Shift+L | show or hide the activity log |
| Ctrl+Shift+U | switch the UI language |
| F1 | keyboard shortcuts |
| Ctrl+Q | quit |

## 5. Screenshot inventory

All images are real renders of the running client (`scripts/ui_screenshots.py`: offscreen
platform, window 1440×900, a live `polmon-backend` with an API token, the `l0-office` topology
and the `office-sweep` scenario). CI renders the same set, plus the English UI, as the
`ui-screenshots` artifact. Details: [ui/SCREENSHOTS.md](ui/SCREENSHOTS.md).

### Before / after

The *before* images are the v0.3.2 client (commit `cfa3f18`, English, pre-Phase IV); the
*after* images are this version in Russian, the default.

| Screen | Before (v0.3.2) | After |
|--------|-----------------|-------|
| Dashboard | [ui/before/dashboard.png](ui/before/dashboard.png) | [ui/dashboard.png](ui/dashboard.png) |
| Deployment | [ui/before/deployment.png](ui/before/deployment.png) | [ui/deployment.png](ui/deployment.png) |

What changed on these two screens: a dark navigation sidebar replaces the light list; the
connection controls moved into a slim header with the emulation-level pill; identity and
admission limits became aligned key/value cards; live counters became tiles with a metric,
one explanatory line and a sparkline; tables gained monospaced identifiers, right-aligned
numbers and status glyphs; destructive buttons are styled as such and confirmed; empty tables
say what to do next.

### Language switch

| Image | Shows |
|-------|-------|
| [ui/before-switch-ru.png](ui/before-switch-ru.png) | the deployment page in Russian just before the switch |
| [ui/language-switch-en.png](ui/language-switch-en.png) | the same window after *View → Language → English* at run time: same connection, deployment, selection and banner |

### Every screen (Russian)

| Image | Screen |
|-------|--------|
| [ui/local-backend.png](ui/local-backend.png) | *Локальный (только L0)* preset: owned loopback backend, L0-only pill |
| [ui/dashboard.png](ui/dashboard.png) | Обзор: backend identity, admission limits, live resources, recent experiments |
| [ui/topologies.png](ui/topologies.png) | Топологии: editor, validation, nodes/networks inspector, resource fit |
| [ui/validation-error.png](ui/validation-error.png) | a validation problem pointing at its YAML line |
| [ui/deployment.png](ui/deployment.png) | Развёртывание: target, deployments, owned resources, counters |
| [ui/admission-rejected.png](ui/admission-rejected.png) | a refusal by admission control naming the limit |
| [ui/scenarios.png](ui/scenarios.png) | Сценарии: a finished experiment with per-action status |
| [ui/telemetry.png](ui/telemetry.png) | Телеметрия: filtered event stream, payload, capture summary |
| [ui/reports.png](ui/reports.png) | Отчёты: status and expected-versus-actual conditions |
| [ui/report-markdown.png](ui/report-markdown.png) | the report rendered in Russian from its JSON |
| [ui/benchmarks.png](ui/benchmarks.png) | Бенчмарки: a bounded job, its limits and the retained result |
| [ui/dashboard-dark.png](ui/dashboard-dark.png) | the dashboard in the dark theme |
| [ui/scenarios-dark.png](ui/scenarios-dark.png) | the scenario page in the dark theme |

[ui/local-backend-refusal-windows.png](ui/local-backend-refusal-windows.png) is the v0.3.0
Windows-runner render of the L1 refusal (English, before this localization); it is kept as the
Phase III record.
