import time
from pathlib import Path

import pytest
import yaml

from lib.connector import ConnectionPool, load_devices
from lib.db_helper import init_db, insert_result

ROOT = Path(__file__).resolve().parent.parent


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
    with open(ROOT / "configs" / "test_params.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def devices():
    return load_devices()


@pytest.fixture(scope="session")
def connection_pool():
    pool = ConnectionPool()
    yield pool
    pool.close_all()


@pytest.fixture(autouse=True)
def record_test_result(request, firmware_version):
    start = time.time()
    yield
    duration_ms = int((time.time() - start) * 1000)
    rep = getattr(request.node, "rep_call", None)
    if rep is None:
        return
    status = "PASS" if rep.passed else "FAIL"
    error_message = str(rep.longrepr) if rep.failed else None
    insert_result(
        test_name=request.node.nodeid,
        status=status,
        firmware_version=firmware_version,
        duration_ms=duration_ms,
        error_message=error_message,
    )


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
