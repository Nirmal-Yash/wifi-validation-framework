from __future__ import annotations
import os, sqlite3, subprocess, sys, time
from pathlib import Path
import pytest, yaml
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
DB_PATH=ROOT/'db'/'results.db'
LIVE_TESTS=os.getenv('NETFORGE_LIVE_TESTS','0')=='1'
def pytest_addoption(parser): parser.addoption('--fw-version',action='store',default='1.0.0')
@pytest.fixture(scope='session')
def fw_version(request): return request.config.getoption('--fw-version')
@pytest.fixture(scope='session')
def test_params():
    default={'timeouts':{'wpa_association_seconds':6,'dhcp_lease_seconds':5},'thresholds':{'minimum_throughput_mbps':15.0,'maximum_latency_ms':45.0}}
    path=ROOT/'config/test_params.yaml'
    if not path.exists(): return default
    with path.open(encoding='utf-8') as fh: loaded=yaml.safe_load(fh) or {}
    return {**default,**loaded}
@pytest.fixture(scope='session')
def system_config():
    with (ROOT/'config/devices.yaml').open(encoding='utf-8') as fh: raw=yaml.safe_load(fh) or {}
    nodes=raw.setdefault('nodes',{})
    nodes.setdefault('ap',{'namespace':'ap_ns','interface':'wlan0','config_path':'config/ap.conf'})
    nodes.setdefault('client',{'namespace':'client_ns','interface':'wlan1','config_path':'config/client.conf'})
    nodes.setdefault('monitor',{'namespace':'monitor_ns','interface':'wlan2'})
    return raw
def ensure_database(version):
    from db.init_db import initialize
    initialize(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('INSERT OR IGNORE INTO firmware_metadata(firmware_version) VALUES (?)',(version,)); conn.commit()
@pytest.fixture(scope='session',autouse=True)
def database_bootstrap(fw_version): ensure_database(fw_version)
def require_live_environment():
    if not LIVE_TESTS: pytest.skip('Privileged network test disabled; set NETFORGE_LIVE_TESTS=1 to run it')
@pytest.fixture(scope='session',autouse=True)
def live_lab():
    if not LIVE_TESTS:
        yield
        return
    subprocess.run(['sudo','-v'],check=True)
    setup=subprocess.run(['sudo','bash',str(ROOT/'scripts/setup_topology.sh')],capture_output=True,text=True)
    if setup.returncode!=0:
        raise RuntimeError(f'NetForge Tier-1 lab provisioning failed:\n{setup.stdout}\n{setup.stderr}')
    try:
        yield
    finally:
        subprocess.run(['sudo','bash',str(ROOT/'scripts/teardown_topology.sh')],check=False)
@pytest.fixture(scope='function',autouse=True)
def lifecycle_management(request):
    if 'system_config' not in request.fixturenames and 'async_sniffer' not in request.fixturenames:
        yield; return
    require_live_environment()
    system_config=request.getfixturevalue('system_config'); nodes=system_config['nodes']; ap=nodes['ap']; client=nodes['client']
    subprocess.run('sudo killall hostapd dnsmasq wpa_supplicant iperf3 dhclient tcpdump 2>/dev/null',shell=True)
    dns_proc=hostapd_proc=None
    try:
        subprocess.run(f"sudo ip netns exec {ap['namespace']} ip addr flush dev {ap['interface']}",shell=True,check=False)
        subprocess.run(f"sudo ip netns exec {ap['namespace']} ip addr add 192.168.50.1/24 dev {ap['interface']}",shell=True,check=False)
        dns_proc=subprocess.Popen(['sudo','ip','netns','exec',ap['namespace'],'dnsmasq',f"--interface={ap['interface']",'--dhcp-range=192.168.50.10,192.168.50.50,255.255.255.0,12h','--no-daemon'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        hostapd_proc=subprocess.Popen(['sudo','ip','netns','exec',ap['namespace'],'hostapd',str(ROOT/ap['config_path'])],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        time.sleep(2)
        if hostapd_proc.poll() is not None:
            raise RuntimeError('hostapd exited during Tier-1 setup; run sudo ip netns exec ap_ns hostapd -dd /home/yash/Desktop/Netforge/config/ap.conf for diagnostics')
        subprocess.run(['sudo','ip','netns','exec',client['namespace'],'ip','link','set',client['interface'],'up'],check=True)
        subprocess.run(['sudo','ip','netns','exec',client['namespace'],'wpa_supplicant','-B','-i',client['interface'],'-c',str(ROOT/client['config_path'])],check=False)
        time.sleep(3)
        subprocess.run(['sudo','ip','netns','exec',client['namespace'],'dhclient','-1',client['interface']],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        yield
    finally:
        for proc in (hostapd_proc,dns_proc):
            if proc:
                proc.terminate()
                try: proc.wait(timeout=3)
                except subprocess.TimeoutExpired: proc.kill()
        subprocess.run('sudo killall hostapd dnsmasq wpa_supplicant dhclient iperf3 tcpdump 2>/dev/null',shell=True)
@pytest.fixture(scope='function')
def async_sniffer(request,system_config):
    require_live_environment(); monitor=system_config['nodes']['monitor']; pcap_dir=ROOT/system_config.get('target_environment',{}).get('log_directory','artifacts/pcaps'); pcap_dir.mkdir(parents=True,exist_ok=True); pcap_path=pcap_dir/f'{request.node.name}.pcap'; tmp=Path('/tmp')/f'netforge-{request.node.name}.pcap'
    for path in (pcap_path,tmp):
        if path.exists(): path.unlink()
    proc=subprocess.Popen(['sudo','ip','netns','exec',monitor['namespace'],'tcpdump','-i',monitor['interface'],'-w',str(tmp),'-U'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); time.sleep(1)
    try: yield str(tmp)
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()
        if tmp.exists(): subprocess.run(['sudo','mv',str(tmp),str(pcap_path)],check=False); subprocess.run(['sudo','chown',str(os.getuid()),str(pcap_path)],check=False)
@pytest.hookimpl(tryfirst=True,hookwrapper=True)
def pytest_runtest_makereport(item,call):
    outcome=yield; report=outcome.get_result()
    if report.when!='call': return
    try:
        with sqlite3.connect(DB_PATH) as conn: conn.execute('INSERT INTO test_logs(firmware_version,test_name,status,execution_time,error_message,pcap_path) VALUES(?,?,?,?,?,?)',(item.config.getoption('--fw-version'),item.name,report.outcome.upper(),report.duration,str(report.longrepr) if report.failed else '',f'artifacts/pcaps/{item.name}.pcap')); conn.commit()
    except sqlite3.Error: pass
