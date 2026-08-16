from __future__ import annotations

from pathlib import Path

from engine.execution_store import connect, create_execution, get_execution, record_test_results
from engine.regression_engine import compare_value


def test_execution_is_persisted_with_reproducibility_metadata():
    execution_id = create_execution(
        firmware_version="test-1.0",
        suite_name="unit",
        triggered_by="pytest",
        environment="tier1",
        notes="unit test",
        command="python -m pytest",
    )
    execution = get_execution(execution_id)
    assert execution is not None
    assert execution["status"] == "QUEUED"
    assert execution["phase"] == "QUEUED"
    assert execution["firmware_version"] == "test-1.0"
    assert execution["suite_name"] == "unit"
    assert execution["triggered_by"] == "pytest"
    assert execution["environment"] == "tier1"
    assert execution["events"]


def test_junit_results_are_normalized(tmp_path: Path):
    junit = tmp_path / "results.xml"
    junit.write_text(
        """<testsuite tests='3' failures='1' errors='1' skipped='0'>
        <testcase classname='tests.test_auth' name='test_auth' time='0.12'/>
        <testcase classname='tests.test_dhcp' name='test_dhcp' time='0.04'><failure message='no lease'>failed</failure></testcase>
        <testcase classname='tests.test_enterprise' name='test_eap' time='0.20'><error message='timeout'>error</error></testcase>
        </testsuite>""",
        encoding="utf-8",
    )
    execution_id = create_execution(firmware_version="junit-test", suite_name="unit")
    counts = record_test_results(execution_id, junit)
    assert counts == {"total": 3, "passed": 1, "failed": 1, "blocked": 0, "skipped": 0, "errors": 1}
    execution = get_execution(execution_id)
    assert execution is not None
    assert len(execution["results"]) == 3
    assert execution["failed"] == 1
    assert execution["errors"] == 1


def test_regression_comparison_direction():
    bad_throughput = compare_value(80.0, 100.0, 10.0, "lower_is_bad")
    assert bad_throughput["regression"] is True
    assert round(bad_throughput["delta_percent"], 1) == -20.0
    good_throughput = compare_value(105.0, 100.0, 10.0, "lower_is_bad")
    assert good_throughput["regression"] is False


def test_execution_schema_contains_phase():
    with connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(executions)")}
    assert "phase" in columns
