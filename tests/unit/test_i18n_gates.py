"""The translation gates pass on the client and demonstrably fail on violations."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import i18n_audit  # noqa: E402

from polmon.client import locales  # noqa: E402


def rules(source: str) -> list[str]:
    return [finding.rule for finding in i18n_audit.lint_source(source)]


def test_client_has_no_hard_coded_user_facing_literals() -> None:
    assert [str(finding) for finding in i18n_audit.lint()] == []


@pytest.mark.parametrize(
    "source",
    [
        'button = QPushButton("Deploy")',
        'widget.setToolTip("Stops the running experiment")',
        'label.setText("Развернуть")',
        'QMessageBox.warning(self, "Error", message)',
        'status = f"Deployed {count} nodes to the backend"',
        'MESSAGE = "The backend is not reachable"',
        'combo.addItem("Local backend")',
    ],
)
def test_lint_flags_hard_coded_text(source: str) -> None:
    assert rules(source), source


@pytest.mark.parametrize(
    "source",
    [
        'button = QPushButton(tr("deployment.deploy"))',
        'bind(button, "setText", "deployment.deploy")',
        'combo.addItem("", "local")',
        'key = f"page.{name}.title"',
        'session.log(Msg("log.done", name=name), "warning")',
        'raise ValueError("unexpected response from the backend")',
        'reason = text.removeprefix("unable to reach backend: ")',
        'pattern = "*.yml *.yaml"',
        'timeout.setSuffix(" s")',  # unit symbols are not translated
        'label.setText("Local backend")  # i18n: allow',
        'def f():\n    """Explain in plain English what happens."""',
    ],
)
def test_lint_accepts_catalog_use_and_machine_text(source: str) -> None:
    assert rules(source) == [], source


def test_lint_script_fails_on_an_injected_literal(tmp_path: Path) -> None:
    """The CLI exits 1 when a real client module gains a literal (CI-visible proof)."""
    original = (ROOT / "src/polmon/client/pages/dashboard.py").read_text(encoding="utf-8")
    broken = tmp_path / "dashboard.py"
    broken.write_text(original + '\nBROKEN = QPushButton("Deploy topology")\n', encoding="utf-8")
    script = ROOT / "scripts/i18n-lint.py"
    failing = subprocess.run(
        [sys.executable, str(script), str(broken)], capture_output=True, text=True, check=False
    )
    assert failing.returncode == 1
    assert "literal passed to a Qt text API: 'Deploy topology'" in failing.stdout
    clean = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )
    assert clean.returncode == 0, clean.stdout


def test_catalogs_are_complete() -> None:
    assert i18n_audit.completeness() == []


@pytest.mark.parametrize(
    ("language", "key", "value", "expected"),
    [
        ("ru", "common.close", None, "ru: missing key common.close"),
        ("ru", "log.done", "Готово", "log.done: placeholders differ"),
        ("ru", "common.close", "Close", "ru: common.close: untranslated words ['Close']"),
        ("en", "common.close", "Закрыть", "en: common.close: Cyrillic in the English catalog"),
        ("ru", "common.close", "  ", "ru: common.close: empty"),
        ("ru", "common.close", "Закрыть лог", "ru: common.close: glossary: use «журнал действий»"),
        ("ru", "common.close", "Развертывание", "ru: common.close: glossary: use «развёртывание"),
    ],
)
def test_completeness_detects_broken_catalogs(
    monkeypatch: pytest.MonkeyPatch, language: str, key: str, value: str | None, expected: str
) -> None:
    catalog = dict(locales.CATALOGS[language])
    if value is None:
        del catalog[key]
    else:
        catalog[key] = value
    monkeypatch.setitem(locales.CATALOGS, language, catalog)
    assert any(error.startswith(expected) for error in i18n_audit.completeness())


def test_completeness_detects_wrong_plural_forms(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = dict(locales.CATALOGS["ru"])
    plural = next(key for key, value in catalog.items() if isinstance(value, dict))
    catalog[plural] = {"one": catalog[plural]["one"], "other": catalog[plural]["other"]}
    monkeypatch.setitem(locales.CATALOGS, "ru", catalog)
    assert any("plural forms" in error for error in i18n_audit.completeness())


def test_completeness_detects_unknown_and_unused_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    catalogs = {language: dict(catalog) for language, catalog in locales.CATALOGS.items()}
    for catalog in catalogs.values():
        catalog["common.never_used"] = "x"
        del catalog["common.close"]  # used by code
    for language, catalog in catalogs.items():
        monkeypatch.setitem(locales.CATALOGS, language, catalog)
    errors = i18n_audit.completeness()
    assert "unused key common.never_used" in errors
    assert any(error.startswith("code uses unknown key common.close") for error in errors)


def test_ui_guide_documents_the_enforced_glossary() -> None:
    guide = (ROOT / "docs/UI-GUIDE.md").read_text(encoding="utf-8")
    for term, russian, _ in i18n_audit.GLOSSARY:
        assert f"| {term} | {russian} |" in guide, term


def test_every_backend_message_code_is_translated() -> None:
    codes = i18n_audit.backend_message_codes()
    assert "fidelity.l0_only" in codes and len(codes) > 100
    catalog = locales.CATALOGS["ru"]
    assert sorted(code for code in codes if f"backend.{code}" not in catalog) == []
