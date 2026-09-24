#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, json, subprocess, sys
from dataclasses import asdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from lib.repositories import SQLiteDatabase
from lib.services import RegressionIntelligenceService, RunService, TestRegistry
from lib.services.release_gate import ReleaseGateEvaluator, ReleaseGateInput

def compile_sources():
    for root in ('lib','dashboard','regression','scripts','ci_tests'):
        for path in (ROOT/root).rglob('*.py'): ast.parse(path.read_text(encoding='utf-8'),filename=str(path))

def run_core_tests(): subprocess.run([sys.executable,'-m','pytest','ci_tests','-q'],cwd=ROOT,check=True)

def evaluate_run(db_path, baseline_run_id, current_run_id, environment_class):
    db=SQLiteDatabase(db_path); db.initialize(); service=RunService.from_sqlite(db); registry=TestRegistry.default()
    if current_run_id is None:
        runs=service.run_repository.list()
        if not runs: raise RuntimeError('no persisted Run exists in release database')
        current_run_id=max(runs, key=lambda run: (run.created_at, run.run_id)).run_id
    report=RegressionIntelligenceService(run_service=service,test_registry=registry).compare_runs(
        baseline_run_id=baseline_run_id,current_run_id=current_run_id,
        baseline_environment_class=environment_class,current_environment_class=environment_class)
    current=service.run_repository.get(current_run_id)
    attempts=sorted(service.attempt_repository.list_for_run(current_run_id),key=lambda x:x.number)
    results=tuple(service.test_result_repository.list_for_attempt(attempts[-1].attempt_id)) if attempts else ()
    required_list=[]
    for selected in current.selected_tests:
        try:
            required_list.append(registry.get(selected).test_id)
        except KeyError:
            required_list.append(registry.resolve_or_fallback(selected).test_id)
    required=tuple(dict.fromkeys(required_list))
    decision=ReleaseGateEvaluator().evaluate(ReleaseGateInput(
        run_lifecycle=current.lifecycle.value,lab_health=current.environment_health.value if current.environment_health else None,
        baseline_available=not report.no_baseline,required_test_ids=required,observed_test_ids=tuple(x.test_id for x in results),
        test_statuses={x.test_id:x.status.value for x in results},evidence_states={x.test_id:x.evidence_state.value for x in results},
        regression_classifications={x.test_id:x.classification.value for x in report.assessments}))
    return report,decision

def main():
    p=argparse.ArgumentParser(); p.add_argument('--skip-core-tests',action='store_true'); p.add_argument('--db',type=Path); p.add_argument('--baseline-run-id'); p.add_argument('--current-run-id'); p.add_argument('--environment-class',default='VIRTUAL_WIFI'); p.add_argument('--output',type=Path)
    a=p.parse_args(); compile_sources()
    if not a.skip_core_tests: run_core_tests()
    if a.baseline_run_id is not None and a.db is None: p.error('--db is required when --baseline-run-id is supplied')
    if a.db is not None and a.baseline_run_id is None: p.error('--baseline-run-id is required when --db is supplied')
    if a.db is not None:
        report,decision=evaluate_run(a.db,a.baseline_run_id,a.current_run_id,a.environment_class)
        payload={'status':decision.status.value,'summary':decision.summary,'issues':[asdict(x) for x in decision.issues],
                 'regression':{'baseline_run_id':report.baseline_run_id,'current_run_id':report.current_run_id,'comparability':report.comparability.value,'reason':report.reason,
                               'assessments':[{'test_id':x.test_id,'classification':x.classification.value,'reason':x.reason} for x in report.assessments]}}
        print(json.dumps(payload,indent=2,sort_keys=True))
        if a.output: a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding='utf-8')
        return 0 if decision.accepted else 1
    print('Internal CI core gate accepted: source parsing and CI contract tests completed.')
    return 0

if __name__=='__main__': raise SystemExit(main())