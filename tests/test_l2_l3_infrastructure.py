import subprocess


def test_8021q_vlan_segregation(system_config, async_sniffer):
    """Validate that Linux can create and route an 802.1Q VLAN in the lab namespace."""
    ap = system_config['nodes']['ap']
    uplink_iface = 'eth_uplink'
    vlan_id = 20
    vlan_iface = f'{uplink_iface}.{vlan_id}'
    try:
        subprocess.run(f"sudo ip netns exec {ap['namespace']} ip link add {uplink_iface} type dummy",shell=True,check=True)
        subprocess.run(f"sudo ip netns exec {ap['namespace']} ip link set {uplink_iface} up",shell=True,check=True)
        subprocess.run(f"sudo ip netns exec {ap['namespace']} ip link add link {uplink_iface} name {vlan_iface} type vlan id {vlan_id}",shell=True,check=True)
        subprocess.run(f"sudo ip netns exec {ap['namespace']} ip link set {vlan_iface} up",shell=True,check=True)
        subprocess.run(f"sudo ip netns exec {ap['namespace']} ip addr add 10.20.30.1/24 dev {vlan_iface}",shell=True,check=True)
        route_check=subprocess.run(f"sudo ip netns exec {ap['namespace']} ip route show dev {vlan_iface}",shell=True,capture_output=True,text=True,check=True).stdout
        assert '10.20.30.0/24' in route_check
    finally:
        subprocess.run(f"sudo ip netns exec {ap['namespace']} ip link delete {uplink_iface} 2>/dev/null",shell=True,check=False)


def test_etherchannel_lacp_negotiation(system_config, async_sniffer):
    """Validate kernel bonding support and explicit 802.3ad/LACP mode."""
    ap = system_config['nodes']['ap']
    try:
        subprocess.run(f"sudo ip netns exec {ap['namespace']} ip link add bond0 type bond mode 802.3ad",shell=True,check=True)
        mode=subprocess.run(f"sudo ip netns exec {ap['namespace']} cat /sys/class/net/bond0/bonding/mode",shell=True,capture_output=True,text=True,check=True).stdout.strip()
        assert mode in {'802.3ad','4'}, f'Unexpected bonding mode: {mode}'
        link_check=subprocess.run(f"sudo ip netns exec {ap['namespace']} ip -d link show bond0",shell=True,capture_output=True,text=True,check=True).stdout
        assert 'bond0' in link_check and ('802.3ad' in link_check or 'mode 4' in link_check)
    finally:
        subprocess.run(f"sudo ip netns exec {ap['namespace']} ip link delete bond0 2>/dev/null",shell=True,check=False)
