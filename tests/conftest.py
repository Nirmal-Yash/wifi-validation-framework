import pytest, yaml
from lib.connector import load_devices

@pytest.fixture(scope="session")
def params():
    with open("configs/test_params.yaml") as f:
        return yaml.safe_load(f)

@pytest.fixture(scope="session")
def devices():
    return load_devices()
