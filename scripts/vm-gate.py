#!/usr/bin/env python3
"""Единый запуск проверок на настоящих гостях KVM с записью доказательств.

Один вызов на хосте с KVM даёт каталог с readiness, junit, выводом pytest, строками
REAL-VM-EVIDENCE и summary.json. Пропуск и недоступная среда — NOT_RUN, а не успех.
Коды выхода: 0 — PASS во всех режимах, 1 — FAIL, 2 — NOT_RUN.

    scripts/vm-gate.py --image IMG.qcow2 [--manifest M.json] [--mode userns|netns|both]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_PREFIX = "REAL-VM-EVIDENCE "
PASS, FAIL, NOT_RUN = "PASS", "FAIL", "NOT_RUN"


def classify(junit_text: str | None, returncode: int) -> tuple[str, dict]:
    """PASS только если тесты выполнены: ни один не пропущен, не упал и хотя бы один был."""
    if returncode == 2 and not junit_text:
        return NOT_RUN, {"tests": 0}
    if not junit_text:
        return FAIL, {"tests": 0, "reason": "no junit report"}
    suite = ET.fromstring(junit_text)
    if suite.tag == "testsuites":
        suite = suite[0]
    counts = {
        key: int(suite.get(key, 0)) for key in ("tests", "failures", "errors", "skipped")
    }
    if counts["failures"] or counts["errors"] or returncode not in (0, 5):
        return FAIL, counts
    if counts["tests"] == 0 or counts["skipped"]:
        return NOT_RUN, counts
    return PASS, counts


def overall(statuses: list[str]) -> str:
    if FAIL in statuses:
        return FAIL
    if not statuses or NOT_RUN in statuses:
        return NOT_RUN
    return PASS


def evidence_lines(text: str) -> list[dict]:
    found = []
    for line in text.splitlines():
        if line.startswith(EVIDENCE_PREFIX):
            found.append(json.loads(line[len(EVIDENCE_PREFIX) :]))
    return found


def _capture(argv: list[str]) -> str | None:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=20, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def host_facts() -> dict:
    cpu = ""
    with_virt = False
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
        cpu = re.search(r"model name\s*:\s*(.+)", cpuinfo).group(1)
        with_virt = bool(re.search(r"^flags.*\b(vmx|svm)\b", cpuinfo, re.M))
    except (OSError, AttributeError):
        pass
    return {
        "platform": platform.platform(),
        "cpu": cpu,
        "cpu_virtualization_flag": with_virt,
        "dev_kvm_accessible": os.access("/dev/kvm", os.R_OK | os.W_OK),
        "qemu": (_capture(["qemu-system-x86_64", "--version"]) or "").splitlines()[:1],
        "git_commit": _capture(["git", "rev-parse", "HEAD"]),
        "git_dirty": bool(_capture(["git", "status", "--porcelain", "--untracked-files=no"])),
    }


def run_mode(mode: str, output: Path, image: Path | None, manifest: Path | None) -> dict:
    junit, log = output / f"junit-{mode}.xml", output / f"pytest-{mode}.txt"
    env = {**os.environ, "POLMON_VM_PYTEST_ARGS": f"--junitxml={junit}"}
    if image:
        env["POLMON_VM_TEST_IMAGE"] = str(image)
    if manifest:
        env["POLMON_VM_TEST_MANIFEST"] = str(manifest)
    started = time.monotonic()
    done = subprocess.run(
        [str(ROOT / "scripts/vm-tests.sh"), mode],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
    )
    log.write_text(done.stdout + done.stderr)
    status, counts = classify(junit.read_text() if junit.exists() else None, done.returncode)
    reason = next(
        (line for line in done.stderr.splitlines() if line.startswith("NOT RUN")), None
    )
    return {
        "mode": mode,
        "status": status,
        "counts": counts,
        "seconds": round(time.monotonic() - started, 1),
        "not_run_reason": reason if status == NOT_RUN else None,
        "evidence": evidence_lines(done.stdout),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("userns", "netns", "both"), default="userns")
    parser.add_argument("--image", type=Path, help="проверенный базовый образ")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, help="каталог доказательств")
    args = parser.parse_args(argv)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    output = (args.output or ROOT / "docs/evidence" / f"vm-gate-{stamp}").resolve()
    output.mkdir(parents=True, exist_ok=False)
    modes = ["userns", "netns"] if args.mode == "both" else [args.mode]
    results = [run_mode(mode, output, args.image, args.manifest) for mode in modes]
    summary = {
        "status": overall([item["status"] for item in results]),
        "started_utc": stamp,
        "host": host_facts(),
        "modes": results,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"vm-gate: {summary['status']} — {output}/summary.json")
    for item in results:
        print(f"  {item['mode']}: {item['status']} {item['counts']} {item['not_run_reason'] or ''}")
    return {PASS: 0, FAIL: 1, NOT_RUN: 2}[summary["status"]]


if __name__ == "__main__":
    sys.exit(main())
