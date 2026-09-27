"""Translation audits for the desktop client (used by i18n-lint.py, i18n-completeness.py, tests).

* ``lint(paths)`` — the hard-coded literal guard: user-visible text must come from the catalogs.
* ``completeness()`` — both catalogs complete, consistent and actually Russian/English.

Only the standard library and the polmon sources are needed (no Qt).
"""

from __future__ import annotations

import ast
import re
import string
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "src/polmon/client"
BACKEND = ROOT / "src/polmon"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# Client modules without user-visible UI text, and why.
EXEMPT_MODULES = {
    "locales/en.py": "the English catalog",
    "locales/ru.py": "the Russian catalog",
    "locales/__init__.py": "catalog registry and the language autonyms",
    "i18n.py": "translation runtime",
    "theme.py": "design tokens and the Qt stylesheet (no words)",
    "app.py": "command-line interface: argparse help and CLI output stay English",
    "selftest.py": "CLI self-test and smoke-start reports (English, parsed by CI)",
    "localprobe.py": "packaged-client acceptance probe (JSON evidence, English)",
    "desktop.py": "the XDG desktop entry file",
    "api.py": "HTTP client internals; ApiClientError text is mapped to catalog messages",
    "local_backend.py": "process manager; its English errors carry message codes for the UI",
    "yamlmap.py": "YAML location helper (no text)",
    "icon.py": "icon drawing (no text)",
}
# Qt methods/constructors whose string argument is shown to the user.
TEXT_APIS = {
    "QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QGroupBox", "QAction", "QMenu",
    "QToolButton", "QListWidgetItem", "QTreeWidgetItem", "QTableWidgetItem", "QDockWidget",
    "setText", "setToolTip", "setStatusTip", "setWhatsThis", "setWindowTitle",
    "setPlaceholderText", "setTitle", "addTab", "setTabText", "addItem", "addItems",
    "setItemText", "addMenu", "setHeaderLabels", "setHorizontalHeaderLabels", "showMessage",
    "information", "warning", "question", "critical", "about", "setAccessibleName",
    "setAccessibleDescription", "setPrefix", "setSuffix", "addButton", "setInformativeText",
    "setDetailedText", "setMarkdown", "setHtml", "setPlainText", "appendPlainText", "log",
    "addRow", "notify",
}
# Words that may appear verbatim in any UI string (machine terms, units, product names).
KEPT_TERMS = {
    "polmon", "polmon-backend", "polmon-client", "L0", "L1", "L2", "TAP", "YAML", "JSON",
    "PCAP", "CSV", "Markdown", "HTTP", "HTTPS", "API", "URL", "IPv4", "IP", "MAC", "ICMP",
    "TCP", "ARP", "TTL", "EtherType", "Ethernet", "RSS", "CPU", "mCPU", "MiB", "GiB", "KiB",
    "MB", "ms", "s", "m", "h", "B", "Ctrl", "Shift", "Esc", "Return", "Enter", "F1", "F5", "Qt",
    "PySide6", "LGPLv3", "Linux", "Windows", "sudo", "iproute2", "setpriv", "ping", "ip",
    "netns", "Wireshark", "ID", "SHA-256", "systemd", "journalctl", "POLMON_API_TOKEN",
    "SmartScreen", "veth", "chmod", "stdout", "stderr", "UTF-8", "unicast", "multicast",
    "loopback", "root", "true", "false", "tcp_probe", "icmp_probe", "detail", "self-test", "user",
    "host", "port", "unit", "user-u", "OK", "PNG",
}
# Messages of raised exceptions are developer diagnostics (the UI maps errors to catalog
# problems), and these calls match text produced by other software.
MATCHING_CALLS = {
    "removeprefix", "removesuffix", "startswith", "endswith", "sub", "match", "fullmatch",
    "search", "compile", "split", "strftime", "strptime", "super",
}
MESSAGE_BOX_STATICS = {"information", "warning", "question", "critical", "about"}
KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]+")
PRAGMA = "i18n: allow"


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.text!r}"


def _words(text: str) -> list[str]:
    """Natural-language words of ``text``: markup, formats, paths and identifiers removed."""
    cleaned = re.sub(r"<[^>]*>|&[a-z]+;", " ", text)  # markup and entities
    cleaned = re.sub(r"%[A-Za-z]", " ", cleaned)  # strftime / printf formats
    cleaned = re.sub(r"\S*[./\\*_=(){}\[\]:#@]\S*", " ", cleaned)  # paths, keys, code
    return [word for word in WORD.findall(cleaned) if word not in KEPT_TERMS]


def _is_prose(text: str) -> bool:
    """Natural-language looking: two or more words that are not machine terms."""
    if KEY.match(text) or "{" in text and ";" in text:  # catalog key or stylesheet
        return False
    return len(_words(text)) >= 2


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _literal_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else " {} " for part in node.values
        )
    return None


def lint_source(source: str, path: str = "<source>") -> list[Finding]:
    """Findings for one module's source (used on the client and on synthetic snippets)."""
    tree = ast.parse(source)
    lines = source.splitlines()
    docstrings = _docstring_nodes(tree)
    findings: list[Finding] = []
    reported: set[int] = set()
    exempt: set[int] = set()

    def allowed(node: ast.AST) -> bool:
        """``# i18n: allow`` on one of the node's lines or on the comment line just above."""
        first, last = node.lineno, getattr(node, "end_lineno", None) or node.lineno
        span = lines[max(first - 2, 0) : last]
        return any(PRAGMA in line for line in span)

    def report(node: ast.AST, rule: str, text: str) -> None:
        if id(node) not in reported and not allowed(node):
            reported.add(id(node))
            findings.append(Finding(path, node.lineno, rule, text))

    # 1. Literals handed to Qt text APIs (any language, any length with letters).
    for node in ast.walk(tree):
        name = _call_name(node) if isinstance(node, ast.Call) else ""
        is_super_init = (
            name == "__init__"
            and isinstance(node.func, ast.Attribute)  # type: ignore[union-attr]
            and isinstance(node.func.value, ast.Call)  # type: ignore[union-attr]
            and _call_name(node.func.value) == "super"  # type: ignore[union-attr]
        )
        if name.endswith(("Error", "Exception")) or name in MATCHING_CALLS or is_super_init:
            exempt.update(id(child) for child in ast.walk(node))  # diagnostics / text matching
        elif isinstance(node, ast.Raise):
            exempt.update(id(child) for child in ast.walk(node))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in TEXT_APIS:
            # The shown text: the first argument (after the parent for QMessageBox statics).
            first = 1 if _call_name(node) in MESSAGE_BOX_STATICS else 0
            candidates = node.args[first:first + 2 if first else first + 1]
            candidates += [kw.value for kw in node.keywords if kw.arg == "text"]
            for argument in candidates:
                text = _literal_text(argument)
                if text is None:
                    continue
                if _words(text) or CYRILLIC.search(text):
                    report(argument, "literal passed to a Qt text API", text)
    # 2. Prose-like literals and composed f-strings anywhere; 3. Cyrillic outside catalogs.
    for node in ast.walk(tree):
        if id(node) in docstrings or id(node) in exempt:
            continue
        if isinstance(node, ast.JoinedStr):
            text = _literal_text(node) or ""
            if CYRILLIC.search(text):
                report(node, "Cyrillic outside the catalogs", text)
            elif _is_prose(text):
                report(node, "composed prose (use a catalog template)", text)
            for part in node.values:
                reported.add(id(part))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in reported:
                continue
            if CYRILLIC.search(node.value):
                report(node, "Cyrillic outside the catalogs", node.value)
            elif _is_prose(node.value):
                report(node, "prose literal (use a catalog key)", node.value)
    return sorted(findings, key=lambda item: (item.path, item.line))


def client_modules() -> list[Path]:
    return sorted(
        path
        for path in CLIENT.rglob("*.py")
        if path.relative_to(CLIENT).as_posix() not in EXEMPT_MODULES
    )


def lint(paths: Iterable[Path] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths if paths is not None else client_modules():
        relative = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
        findings += lint_source(path.read_text(encoding="utf-8"), relative)
    return findings


# -- completeness -------------------------------------------------------------------------------


def _placeholders(value: str | dict[str, str]) -> set[str]:
    values = value.values() if isinstance(value, dict) else [value]
    return {name for text in values for _, name, _, _ in string.Formatter().parse(text) if name}


def _texts(value: str | dict[str, str]) -> list[str]:
    return list(value.values()) if isinstance(value, dict) else [value]


def literal_keys() -> dict[str, list[str]]:
    """Catalog-key-shaped literals in client code → where they appear."""
    from polmon.client.locales import CATALOGS

    namespaces = {key.split(".", 1)[0] for key in CATALOGS["en"]} - {"polmon"}
    found: dict[str, list[str]] = {}
    for path in CLIENT.rglob("*.py"):
        relative = path.relative_to(CLIENT).as_posix()
        if relative.startswith("locales/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parts = {
            id(value)
            for node in ast.walk(tree)
            if isinstance(node, ast.JoinedStr)
            for value in node.values
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or id(node) in parts:
                continue
            value = node.value
            if isinstance(value, str) and KEY.match(value) and value.split(".")[0] in namespaces:
                found.setdefault(value, []).append(f"{relative}:{node.lineno}")
    return found


def problem_keys() -> set[str]:
    keys: set[str] = set()
    for path in CLIENT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and _call_name(node) == "Problem" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    keys.add(first.value)
    return keys


def backend_message_codes() -> set[str]:
    """Every message code the backend can send (literal codes plus the generated families)."""
    codes: set[str] = set()
    for path in BACKEND.rglob("*.py"):
        if "client" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.keyword)
                and node.arg == "message_code"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                codes.add(node.value.value)
            if (
                isinstance(node, ast.Call)
                and _call_name(node) == "CodedValueError"
                and len(node.args) > 1
                and isinstance(node.args[1], ast.Constant)
            ):
                codes.add(str(node.args[1].value))
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=False):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "message_code"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    ):
                        codes.add(value.value)
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and re.fullmatch(r"(experiment|benchmark)\.[a-z_]+", node.value)
            ):
                codes.add(node.value)  # codes assigned to job/experiment records
    from polmon.core.errors import ConfigurationError, PolmonError
    from polmon.resources.policy import ResourceLimitError

    classes = (PolmonError, ConfigurationError, ResourceLimitError)
    codes |= {f"generic.{cls.code}" for cls in classes}
    codes |= {"topology.yaml_invalid", "scenario.yaml_invalid"}
    return codes


def required_families() -> dict[str, set[str]]:
    """Keys the code builds dynamically (``f"status.{value}"``…) and must all exist."""
    from polmon.client import theme
    from polmon.client.mainwindow import FEATURE_EXPERIMENTS, FEATURE_TOPOLOGIES, PAGES
    from polmon.client.models import CATEGORIES
    from polmon.client.pages import FILE_PATTERNS
    from polmon.client.pages.benchmarks import KINDS
    from polmon.client.state import ConnectionState
    from polmon.topology.io import YAML_PROBLEMS

    statuses = (
        theme.SUCCESS_STATES | theme.INFO_STATES | theme.WARNING_STATES | theme.DANGER_STATES
        | {state.value for state in ConnectionState}
        | {"destroyed", "validated", "new", "reset", "pending", "done", "yes", "no"}
    )
    local_codes = set()
    for node in ast.walk(ast.parse((CLIENT / "local_backend.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and _call_name(node) == "LocalBackendError":
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                local_codes.add(str(node.args[1].value))
            elif len(node.args) > 1 and isinstance(node.args[1], ast.IfExp):
                for branch in (node.args[1].body, node.args[1].orelse):
                    if isinstance(branch, ast.Constant):
                        local_codes.add(str(branch.value))
    local_codes |= {"failed", "exited", "not_ready", "not_started"}
    pages = [page.key for page in PAGES]
    return {
        "backend": {f"backend.{code}" for code in backend_message_codes()},
        "yaml": {f"backend.yaml.{code}" for _, code in YAML_PROBLEMS} | {"backend.yaml.syntax"},
        "status": {f"status.{value}" for value in statuses},
        "pages": {f"page.{key}.{part}" for key in pages for part in ("title", "subtitle")},
        "categories": {f"category.{value}" for value in CATEGORIES},
        "benchmark kinds": {
            f"benchmark.{family}.{kind}" for kind in KINDS for family in ("kind", "kind_short")
        } | {f"benchmark.kind.{kind}.limitation" for kind in KINDS},
        "connection": {"connection.mode.local", "connection.mode.remote"}
        | {f"connection.state.{state.value}" for state in ConnectionState},
        "themes": {f"theme.{name}" for name in theme.THEMES},
        "fidelity": {f"fidelity.{v}" for v in ("l0_only", "linux_lab")}
        | {f"fidelity.badge.{v}{tip}" for v in ("l0_only", "linux_lab") for tip in ("", ".tip")},
        "features": {f"feature.{FEATURE_TOPOLOGIES}", f"feature.{FEATURE_EXPERIMENTS}"},
        "files": {f"files.{kind}" for kind in FILE_PATTERNS},
        "documents": {f"document.{kind}" for kind in ("topology", "scenario", "report")},
        "local": {f"local.{code}" for code in local_codes},
        "conditions": {f"condition.role.{r}" for r in ("success_requirement", "failure_trigger")},
        "fits": {f"topologies.fit.{v}" for v in ("fits", "exceeds", "memory_fits",
                                                 "memory_exceeds", "unsupported")},
        "targets": {f"deployment.target.{v}" for v in ("editor", "loaded", "deployed")},
        "problems": {f"{key}.title" for key in problem_keys()},
        "limits": {f"limit.{name}" for name in (
            "endpoint_count", "active_namespaces", "available_memory", "concurrent_experiments",
            "duration_seconds", "data_directory", "disk_free", "max_endpoints", "max_namespaces",
            "memory_reserve_mb", "max_run_seconds", "concurrent_benchmarks",
            "active_experiments", "benchmark_jobs")}
        | {f"limit.field.{name}" for name in (
            "projected", "limit", "active", "requested", "minimum",
            "required_mb_including_reserve", "available_mb", "used_mb", "free_mb", "limit_mb",
            "reserve_mb", "next_experiment_capture_limit_mb", "size_bytes")},
    }


# Families whose members are optional (only some columns have explanations, etc.).
OPTIONAL_PREFIXES = ("measure.", "backend.pydantic.", "backend.generic.")


def _latin_prose(text: str) -> list[str]:
    """Purely Latin words of a Russian text that are not kept terms (``IPv4``, ``MAC-адрес``
    and other mixed tokens are deliberate)."""
    cleaned = re.sub(r"\{[a-z_]+\}", " ", text)
    cleaned = re.sub(r"`[^`]*`|«[a-z_]+»|“[^”]*”", " ", cleaned)
    cleaned = re.sub(r"[a-z]+://\S*|--[a-z-]+|\S*[/_\\.]\S*[A-Za-z]\S*", " ", cleaned)
    tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё'’-]+", cleaned)
    return [
        token
        for token in tokens
        if re.fullmatch(r"[A-Za-z'’]+", token) and token not in KEPT_TERMS and len(token) > 1
    ]


def completeness() -> list[str]:
    from polmon.client.locales import CATALOGS

    errors: list[str] = []
    en, ru = CATALOGS["en"], CATALOGS["ru"]
    for missing in sorted(set(en) - set(ru)):
        errors.append(f"ru: missing key {missing}")
    for missing in sorted(set(ru) - set(en)):
        errors.append(f"en: missing key {missing}")
    for key in sorted(set(en) & set(ru)):
        if _placeholders(en[key]) != _placeholders(ru[key]):
            errors.append(f"{key}: placeholders differ ({_placeholders(en[key])} vs "
                          f"{_placeholders(ru[key])})")
        for language, value, forms in (("en", en[key], {"one", "other"}),
                                       ("ru", ru[key], {"one", "few", "many", "other"})):
            if isinstance(value, dict) and set(value) != forms:
                errors.append(f"{language}: {key}: plural forms {sorted(value)} != {sorted(forms)}")
            for text in _texts(value):
                if not text.strip():
                    errors.append(f"{language}: {key}: empty")
        for text in _texts(ru[key]):
            prose = _latin_prose(text)
            if prose:
                errors.append(f"ru: {key}: untranslated words {prose}: {text!r}")
        for text in _texts(en[key]):
            if CYRILLIC.search(text):
                errors.append(f"en: {key}: Cyrillic in the English catalog: {text!r}")
    used = literal_keys()
    codes = backend_message_codes()
    for key, places in sorted(used.items()):
        if key not in en and key not in codes and f"{key}.title" not in en:
            errors.append(f"code uses unknown key {key} ({places[0]})")
    families = required_families()
    required: set[str] = set()
    for family, keys in families.items():
        for key in sorted(keys):
            if key not in en:
                errors.append(f"{family}: missing {key}")
        required |= keys
    # A problem key stands for its whole family: title, hint and detail.
    families = set(used) | problem_keys()
    referenced = set(used) | required | {
        f"{key}.{part}" for key in families for part in ("title", "hint", "detail")
    }
    for key in sorted(en):
        if key not in referenced and not key.startswith(OPTIONAL_PREFIXES):
            errors.append(f"unused key {key}")
    return errors


def summary() -> dict[str, int]:
    from polmon.client.locales import CATALOGS

    plural = sum(isinstance(value, dict) for value in CATALOGS["en"].values())
    return {
        "keys": len(CATALOGS["en"]),
        "plural keys": plural,
        "backend message codes": len(backend_message_codes()),
        "literal keys in code": len(literal_keys()),
    }
