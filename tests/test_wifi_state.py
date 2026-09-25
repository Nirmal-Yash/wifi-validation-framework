from lib.services.wifi_state import assess_wifi_association


COMPLETED_STATUS = """bssid=02:00:00:00:00:00
freq=2437
ssid=TestNet_5G
id=0
mode=station
pairwise_cipher=CCMP
group_cipher=CCMP
key_mgmt=WPA2-PSK
wpa_state=COMPLETED
"""

CONNECTED_LINK = """Connected to 02:00:00:00:00:00 (on wlan0)
	SSID: TestNet_5G
	freq: 2437
	signal: -20 dBm
"""


def test_explicit_wpa_completed_is_accepted():
    state = assess_wifi_association(
        wpa_status=COMPLETED_STATUS,
        iw_link=CONNECTED_LINK,
        expected_ssid="TestNet_5G",
        require_wpa2=True,
    )
    assert state.connected is True
    assert state.wpa_state == "COMPLETED"


def test_driver_link_is_fallback_when_wpa_state_is_missing():
    status = COMPLETED_STATUS.replace("wpa_state=COMPLETED
", "")
    state = assess_wifi_association(
        wpa_status=status,
        iw_link=CONNECTED_LINK,
        expected_ssid="TestNet_5G",
        require_wpa2=True,
    )
    assert state.connected is True
    assert state.wpa_state is None


def test_wrong_ssid_is_rejected():
    state = assess_wifi_association(
        wpa_status=COMPLETED_STATUS,
        iw_link=CONNECTED_LINK.replace("TestNet_5G", "OtherNet"),
        expected_ssid="TestNet_5G",
        require_wpa2=True,
    )
    assert state.connected is False


def test_non_completed_explicit_state_is_not_overridden_by_driver_link():
    status = COMPLETED_STATUS.replace("wpa_state=COMPLETED", "wpa_state=DISCONNECTED")
    state = assess_wifi_association(
        wpa_status=status,
        iw_link=CONNECTED_LINK,
        expected_ssid="TestNet_5G",
    )
    assert state.connected is False
