# Phase IV plan: Russian UI localization and interface quality pass

Status: implementation plan, committed before Phase IV product changes. Target release:
**v0.4.0**. `MANDATE-UI-RU.md` is the governing operator order; the Phase II/III security,
isolation, resource and reporting rules stay in force. Phase III was verified and released
(v0.3.0–v0.3.2) before this work started.

## 1. Internationalization architecture

- **Catalogs.** `polmon/client/locales/en.py` and `ru.py` each hold one flat
  `MESSAGES: dict[str, str | dict[str, str]]` keyed by stable dotted identifiers
  (`deploy.action.deploy`, `problem.admission.title`, `backend.fidelity.l0_only`). Values are
  `str.format` templates with named placeholders; plural entries are dictionaries of CLDR forms
  (`one`/`other` for English, `one`/`few`/`many`/`other` for Russian). Python modules rather than
  data files: PyInstaller collects them with no spec changes and they cannot go missing from a
  bundle.
- **Runtime.** `polmon/client/i18n.py` is Qt-free: `tr(key, **params)`, `tr_n(key, count, ...)`,
  `language()`, `set_language()`, and listeners. Widgets are bound, not assigned:
  `bind(widget, "setText", key, **params)` applies the text now and re-applies it on every
  language change (weakly referenced, so bindings never keep widgets alive). Views whose text is
  computed (status line, tiles, tables) implement `retranslate()` and re-render from session
  state. Switching language therefore needs no restart and loses no session state: connection,
  editors, selections, deployments and the owned local backend are untouched.
- **Default and choice.** Russian is the default; *Вид → Язык* (*View → Language*) switches at
  runtime and the choice is stored in `QSettings` (`view/language`). `--language ru|en` and
  `POLMON_LANGUAGE` override it (tests, screenshots, support).
- **Composed messages.** `Problem` stores message keys and parameters and renders on access, so
  a banner shown before a language switch re-renders in the new language.
- **Not translated:** object names, JSON keys, API paths, CLI flags, protocol and model names,
  database fields, unit symbols, topology/scenario/experiment identifiers, and technical terms in
  the glossary's "kept as is" list (L0, L1, TAP, YAML, PCAP, …).

## 2. Backend-originated text: machine code + parameters (approach a)

The backend keeps its English `message` (the Phase III refusal contract and every existing API
consumer stay valid) and adds `message_code` and `params` to every error document:
`{"error": {"code", "message", "message_code", "params", "details"}}`. Every `PolmonError`
raise site in the backend passes a code; validator failures inside the topology/scenario models
raise a coded `ValueError` subclass whose code survives Pydantic wrapping into each
`details.errors[]` item, and Pydantic's own error types are passed through as
`pydantic.<type>`. The client renders `backend.<message_code>` from its catalog. A backend
without codes (older version) still gets a localized category title and hint; the raw backend
text is then shown only as a quoted detail. Rationale: localization stays in one place (the
client), the backend needs no locale negotiation, and codes are testable identifiers. An AST
test fails when a backend raise site has no code.

## 3. Gates

- **Hard-coded literal guard** (`scripts/i18n-lint.py`, run by the unit suite): AST scan of the
  client package; flags string literals passed to Qt text APIs (`QLabel`, `QPushButton`,
  `setText`, `setToolTip`, `setWindowTitle`, `setPlaceholderText`, `addAction`, `QMessageBox`,
  …), prose-like literals and f-strings, and any Cyrillic outside the catalogs. A test proves it
  fails on a deliberately unlocalized string; the failing output is committed as evidence.
- **Completeness** (`scripts/i18n-completeness.py`, CI step on both platforms): identical key
  sets, identical placeholders, complete plural forms, no empty values, no Russian value left in
  English (Latin prose outside the kept-as-is glossary list), no unused and no missing keys (every
  `tr`/`bind` key in the code exists).
- **Screen walk** (GUI test, both languages): every page, menu, header and tooltip of the real
  window; in Russian no visible text may contain English prose, in English no Cyrillic.
- **Tests assert identifiers**: object names, catalog keys, `Problem.key`, backend
  `message_code`; the GUI suite runs under both catalogs in CI.

## 4. Interface quality pass

A deliberate visual system documented in `docs/UI-GUIDE.md`: one accent (a deep teal-blue) on
neutral slate surfaces, semantic success/warning/danger/info colours each checked for ≥ 4.5:1
text contrast by a test, a 4-px spacing scale, a four-step type scale, 28-px controls, a full
QSS (buttons by role — primary, secondary, danger, quiet —, inputs, cards, tables, tabs,
scroll bars, tool tips, status bar), monospaced identifiers in tables, sortable and resizable
tables, empty/loading/error states from one `StateView` component, a status-bar busy indicator
for anything that can take seconds, destructive actions styled and confirmed consistently,
status always shown as text (never colour alone), sane tab order, and the keyboard-shortcut list
inside the UI. Density is preserved: the dashboard keeps every counter and limit visible at
1440×900 without scrolling.

## 5. Evidence and release

Real renders at 1440×900 from live windows against a running backend: every main screen in
Russian, before/after pairs for the dashboard and deployment screens (before = v0.3.2,
`docs/ui/before/`), and the English UI after a runtime switch from Russian. `docs/UI-GUIDE.md`
(tokens, scales, components, glossary, screenshot inventory). CI green on both platforms, version
0.4.0 visible in UI/CLI/API, annotated tag only after the gates pass, release with both
platforms' artifacts and `SHA256SUMS.txt`, and the section-10 milestone report.
