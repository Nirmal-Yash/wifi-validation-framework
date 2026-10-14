import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from lib.services.wifi_state import assess_wifi_association

pytestmark = pytest.mark.real_lab


@pytest.mark.regression
def test_wpa2_authentication(connection_pool, params, metric_logger):
    """Client should be authenticated to the AP with verified WPA2-PSK association."""
    ssid = params["wifi"]["ssid"]
    status = connection_pool.send_command(
        "client_vm",
        "wpa_cli -i wlan0 status 2>/dev/null || wpa_cli status",
    )
    link = connection_pool.send_command(
        "client_vm",
        "iw dev wlan0 link 2>/dev/null || true",
    )
    association = assess_wifi_association(
        wpa_status=status,
        iw_link=link,
        expected_ssid=ssid,
        require_wpa2=True,
    )
    metric_logger.log(1.0 if association.connected else 0.0, "bool")

    assert association.connected, (
        "WPA2 association was not verified. "
        f"wpa_cli status: {status}; iw link: {link}"
    )
