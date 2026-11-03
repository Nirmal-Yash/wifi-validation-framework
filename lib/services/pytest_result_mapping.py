"""Translate pytest phase reports into durable NetRegress TestResult statuses."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lib.domain import TestResultStatus


def map_pytest_reports(
    reports: Mapping[str, Any],
) -> tuple[TestResultStatus, str | None]:
    """Map setup/call/teardown reports without collapsing pytest outcomes.

    Setup and teardown errors are execution errors, assertion failures are FAIL,
    skips remain SKIPPED, xfail remains KNOWN_FAILURE, and xpass remains XPASS.
    """
    setup = reports.get("setup")
    if setup is not None and (
        getattr(setup, "failed", False)
        or getattr(setup, "outcome", None) == "failed"
    ):
        return TestResultStatus.ERROR, str(getattr(setup, "longrepr", "")) or "setup failed"

    call = reports.get("call")
    if call is not None:
        outcome = getattr(call, "outcome", None)
        was_xfail = getattr(call, "wasxfail", None)
        if was_xfail is not None:
            if outcome == "skipped":
                return TestResultStatus.KNOWN_FAILURE, str(getattr(call, "longrepr", "")) or str(was_xfail)
            if outcome in {"passed", "failed"}:
                return TestResultStatus.XPASS, f"Unexpected pass (xfail condition not met): {was_xfail}"
        if outcome == "failed":
            return TestResultStatus.FAIL, str(getattr(call, "longrepr", "")) or "pytest call failed"

    teardown = reports.get("teardown")
    if teardown is not None and (
        getattr(teardown, "failed", False)
        or getattr(teardown, "outcome", None) == "failed"
    ):
        return TestResultStatus.ERROR, str(getattr(teardown, "longrepr", "")) or "teardown failed"

    if call is not None:
        if getattr(call, "outcome", None) == "passed":
            return TestResultStatus.PASS, None
        if getattr(call, "outcome", None) == "skipped":
            return TestResultStatus.SKIPPED, str(getattr(call, "longrepr", "")) or "pytest skipped"

    setup = reports.get("setup")
    if setup is not None and (
        getattr(setup, "skipped", False)
        or getattr(setup, "outcome", None) == "skipped"
    ):
        wasxfail = getattr(setup, "wasxfail", None)
        if wasxfail is not None:
            return TestResultStatus.KNOWN_FAILURE, str(getattr(setup, "longrepr", "")) or str(wasxfail)
        return TestResultStatus.SKIPPED, str(getattr(setup, "longrepr", "")) or "pytest setup skipped"
    return TestResultStatus.UNVALIDATED, "pytest did not produce a conclusive call report"
