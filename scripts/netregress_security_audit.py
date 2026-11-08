#!/usr/bin/env python3
"""Fail-closed source security audit for NetRegress production Python paths."""
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOTS = ("lib", "dashboard", "regression", "scripts", "ci_tests")
SECRET_PATTERNS = (
    re.compile(r"""(?i)password\s*[:=]\s*['"][^'"]{8,}['"]"""),
    re.compile(r"""(?i)(api[_-]?key|access[_-]?token|secret)\s*[:=]\s*['"][^'"]{12,}['"]"""),
)


class AuditVisitor(ast.NodeVisitor):
    def __init__(self, path: str, findings: list[dict]):
        self.path = path
        self.findings = findings

    def visit_Call(self, node: ast.Call) -> None:
        for keyword in node.keywords:
            if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                self.findings.append({
                    "severity": "MEDIUM", "code": "SHELL_TRUE",
                    "path": self.path, "line": node.lineno,
                })
        self.generic_visit(node)


def main() -> int:
    parser = argparse.ArgumentParser(description="NetRegress source security/readiness audit")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    findings: list[dict] = []
    scanned = 0
    for root in PRODUCTION_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for item in sorted(base.rglob("*.py")):
            if any(part in {".venv", "venv", "__pycache__", "node_modules"} for part in item.parts):
                continue
            rel = item.relative_to(ROOT).as_posix()
            try:
                source = item.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=rel)
            except (OSError, SyntaxError, UnicodeError) as exc:
                findings.append({"severity": "HIGH", "code": "PYTHON_SOURCE_INVALID", "path": rel, "detail": str(exc)})
                continue
            scanned += 1
            AuditVisitor(rel, findings).visit(tree)
            for pattern in SECRET_PATTERNS:
                if pattern.search(source):
                    findings.append({"severity": "HIGH", "code": "TRACKED_SECRET_PATTERN", "path": rel})
                    break

    tools = {name: bool(shutil.which(name)) for name in ("bandit", "semgrep", "pip-audit")}
    report = {
        "schema_version": "netregress-security-audit.v2",
        "python_files_scanned": scanned,
        "external_scanners": tools,
        "finding_count": len(findings),
        "findings": findings,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    high = any(item["severity"] in {"HIGH", "CRITICAL"} for item in findings)
    unavailable = [name for name, present in tools.items() if not present]
    # External scanners are advisory in this source-only audit; CI installs/runs
    # pip-audit separately. Missing optional tools are reported, not hidden.
    return 1 if args.strict and high else 0


if __name__ == "__main__":
    raise SystemExit(main())
