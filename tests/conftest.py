import sys
import time
from pathlib import Path

# Bootstrap project root into sys.path before any local package imports
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
import yaml

from lib.connector import ConnectionPool, load_devices
from lib.db_helper import init_db, insert_result


def pytest_addoption(parser):
    parser.addoption(
        "--firmware-version",
        action="store",
        default="v1.0",
        help="Firmware version tag for this test run",
    )


@pytest.fixture(scope="session")
def firmware_version(request):
    return request.config.getoption("--firmware-version")


@pytest.fixture(scope="session")
def params():
    params_path = ROOT / "configs" / "test_params.yaml"
    if not params_path.exists():
        raise FileNotFoundError(f"Configuration file missing: {params_path}")
    with open(params_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def devices():
    return load_devices()


@pytest.fixture(scope="session")
def connection_pool():
    pool = ConnectionPool()
    yield pool
    pool.close_all()


class MetricLogger:
    """Fixture helper to record numerical metrics with units for regression intelligence."""

    def __init__(self, node):
        self._node = node

    def log(self, value, unit):
        try:
            val_float = float(value)
        except (ValueError, TypeError):
            val_float = None
        self._node.user_properties.append(("metric_value", val_float))
        self._node.user_properties.append(("metric_unit", str(unit)))


@pytest.fixture
def metric_logger(request):
    return MetricLogger(request.node)


@pytest.fixture(autouse=True)
def record_test_result(request, firmware_version):
    start = time.time()
    yield
    duration_ms = int((time.time() - start) * 1000)

    rep_call = getattr(request.node, "rep_call", None)
    rep_setup = getattr(request.node, "rep_setup", None)

    if rep_call is not None:
        status = "PASS" if rep_call.passed else "FAIL"
        error_message = str(rep_call.longrepr) if rep_call.failed else None
    elif rep_setup is not None and rep_setup.failed:
        status = "FAIL"
        error_message = f"Setup failed: {rep_setup.longrepr}"
    else:
        # Test skipped or undetermined
        return

    # Extract metrics logged by test
    props = dict(request.node.user_properties)
    metric_val = props.get("metric_value")
    metric_unit = props.get("metric_unit")

    try:
        insert_result(
            test_name=request.node.nodeid,
            status=status,
            firmware_version=firmware_version,
            duration_ms=duration_ms,
            error_message=error_message,
            metric_value=metric_val,
            metric_unit=metric_unit,
        )
    except Exception as db_err:
        # Prevent database insertion errors from failing the test suite
        sys.stderr.write(f"\n[WARN] Failed to insert test result to DB: {db_err}\n")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
