#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, json, re, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PRODUCTION_ROOTS=("lib","dashboard","regression","scripts","ci_tests")
SECRET_PATTERNS=(
    re.compile(r"(?i)password\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|secret)\s*[:=]\s*['\"][^'\"]{12,}['\"]"),
)
class AuditVisitor(ast.NodeVisitor):
    def __init__(self,path,findings):
        self.path=path;self.findings=findings
    def visit_Call(self,node):
        for kw in node.keywords:
            if kw.arg=="shell" and isinstance(kw.value,ast.Constant) and kw.value.value is True:
                self.findings.append({"severity":"MEDIUM","code":"SHELL_TRUE","path":str(self.path),"line":node.lineno})
        self.generic_visit(node)
def main()->int:
    parser=argparse.ArgumentParser(description="NetRegress source security/readiness audit")
    parser.add_argument("--strict",action="store_true")
    args=parser.parse_args()
    findings=[];python_files=[]
    for root in PRODUCTION_ROOTS:
        base=ROOT/root
        if not base.exists():continue
        for item in base.rglob("*.py"):
            python_files.append(item);rel=str(item.relative_to(ROOT))
            try:tree=ast.parse(item.read_text(encoding="utf-8"),filename=rel)
            except (OSError,SyntaxError) as exc:
                findings.append({"severity":"HIGH","code":"PYTHON_SYNTAX","path":rel,"detail":str(exc)});continue
            AuditVisitor(rel,findings).visit(tree)
            text=item.read_text(encoding="utf-8")
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    findings.append({"severity":"HIGH","code":"TRACKED_SECRET_PATTERN","path":rel})
            if rel != "scripts/netregress_security_audit.py":
                for line_no,line in enumerate(text.splitlines(),1):
                    if re.search(r"\b(TODO|FIXME)\b",line):
                        findings.append({"severity":"MEDIUM","code":"TODO_IN_PRODUCTION_PATH","path":rel,"line":line_no})
    tools={tool:bool(shutil.which(tool)) for tool in ("bandit","semgrep","pip-audit")}
    report={"schema_version":"netregress-security-audit.v1","tools":tools,"finding_count":len(findings),"findings":findings}
    print(json.dumps(report,indent=2,sort_keys=True))
    critical=[item for item in findings if item["severity"] in {"HIGH","CRITICAL"}]
    return 1 if args.strict and critical else 0
if __name__=="__main__":
    raise SystemExit(main())
