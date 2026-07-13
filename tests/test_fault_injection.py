import pytest

from lib.fault_injector import clear_conditions, link_down, link_up
from lib.traffic import run_ping


@pytest.mark.regression
def test_fault_injection_link_down_up(params):
    """Link down should cause ping failure; link up should restore connectivity."""
    router_ip = params["network"]["router_ip"]
    iface = params["network"]["client_interface"]

    # Verify baseline connectivity
    result = run_ping(router_ip, count=3)
    assert result["success"], "Baseline ping to router failed before fault injection"

    try:
        link_down(iface)
        result_down = run_ping(router_ip, count=3)
        assert not result_down["success"] or result_down["packet_loss_pct"] > 50, (
            "Ping should fail or have high loss when link is down"
        )
    finally:
        link_up(iface)
        clear_conditions(iface)

    result_up = run_ping(router_ip, count=3)
    assert result_up["success"], "Ping should recover after link is brought back up"
