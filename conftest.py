from __future__ import annotations
import os,time
import pytest

def pytest_configure(config):
    config.addinivalue_line('markers','live: requires privileged Tier-1 networking')

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item,call):
    outcome=yield
    report=outcome.get_result()
    if report.when!='call': return
    execution_id=os.getenv('NETFORGE_EXECUTION_ID')
    if not execution_id:return
    try:
        from engine.execution_store import record_metric
        record_metric(int(execution_id),f'test.duration.{item.name}',float(report.duration),'seconds')
        if report.failed: record_metric(int(execution_id),f'test.failure.{item.name}',1.0,'count')
    except Exception:
        # Metrics are observability, never a reason to turn a real test result into an error.
        pass
