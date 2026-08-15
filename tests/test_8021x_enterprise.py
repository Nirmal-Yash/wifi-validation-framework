from __future__ import annotations

import subprocess
import time
from pathlib import Path


def test_enterprise_8021x_authentication(system_config):
    """Validate a real WPA-Enterprise PEAP authentication exchange in hwsim."""
    root = Path(__file__).resolve().parents[1]
    ap = system_config['nodes']['ap']
    client = system_config['nodes']['client']
    ap_conf = root / 'config' / 'hostapd_enterprise.conf'
    client_conf = root / 'config' / 'wpa_supplicant_enterprise.conf'

    subprocess.run(['sudo','killall','hostapd','wpa_supplicant'],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    ap_proc = subprocess.Popen(['sudo','ip','netns','exec',ap['namespace'],'hostapd',str(ap_conf)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        time.sleep(2)
        assert ap_proc.poll() is None, 'hostapd enterprise daemon exited during startup'
        subprocess.run(['sudo','ip','netns','exec',client['namespace'],'ip','link','set',client['interface'],'up'],check=True)
        subprocess.run(['sudo','ip','netns','exec',client['namespace'],'wpa_supplicant','-B','-i',client['interface'],'-c',str(client_conf)],check=True)
        deadline=time.monotonic()+15
        status=''
        while time.monotonic()<deadline:
            result=subprocess.run(['sudo','ip','netns','exec',client['namespace'],'wpa_cli','-i',client['interface'],'status'],capture_output=True,text=True,check=False)
            status=result.stdout
            if 'wpa_state=COMPLETED' in status:
                break
            time.sleep(.5)
        assert 'wpa_state=COMPLETED' in status, f'WPA-Enterprise authentication did not complete:\n{status}'
    finally:
        subprocess.run(['sudo','killall','wpa_supplicant'],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        ap_proc.terminate()
        try:
            ap_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            ap_proc.kill()
