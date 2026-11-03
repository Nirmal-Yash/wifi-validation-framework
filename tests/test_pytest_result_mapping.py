from types import SimpleNamespace

import pytest

from lib.domain import TestResultStatus
from lib.services.pytest_result_mapping import map_pytest_reports


def report(outcome, *, wasxfail=None, longrepr=None):
    data = {"outcome": outcome, "longrepr": longrepr or outcome}
    if wasxfail is not None:
        data["wasxfail"] = wasxfail
    return SimpleNamespace(**data)


@pytest.mark.parametrize(
    ("reports", "expected"),
    [
        ({"call": report("passed")}, TestResultStatus.PASS),
        ({"call": report("failed")}, TestResultStatus.FAIL),
        ({"call": report("skipped")}, TestResultStatus.SKIPPED),
        ({"call": report("skipped", wasxfail="known issue")}, TestResultStatus.KNOWN_FAILURE),
        ({"call": report("passed", wasxfail="expected failure")}, TestResultStatus.XPASS),
        ({"call": report("failed", wasxfail="strict expected failure")}, TestResultStatus.XPASS),
        ({"setup": report("failed")}, TestResultStatus.ERROR),
        ({"call": report("passed"), "teardown": report("failed")}, TestResultStatus.ERROR),
        ({"setup": report("skipped")}, TestResultStatus.SKIPPED),
        ({"setup": report("skipped", wasxfail="fixture xfail")}, TestResultStatus.KNOWN_FAILURE),
    ],
)
def test_pytest_phase_reports_are_mapped_without_loss(reports, expected):
    status, _ = map_pytest_reports(reports)
    assert status is expected


def test_pytest_pass_has_no_error_message():
    status, error = map_pytest_reports({"call": report("passed")})
    assert status is TestResultStatus.PASS
    assert error is None


def test_missing_call_report_is_unvalidated():
    status, error = map_pytest_reports({})
    assert status is TestResultStatus.UNVALIDATED
    assert "no conclusive call report" in error


def test_assertion_failure_remains_primary_when_teardown_also_fails():
    status, _ = map_pytest_reports(
        {
            "call": report("failed", longrepr="assertion failed"),
            "teardown": report("failed", longrepr="fixture finalizer failed"),
        }
    )
    assert status is TestResultStatus.FAIL
