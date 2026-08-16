#!/usr/bin/env python3
"""Tier-1 Enterprise 802.1X validation harness.

This script is intentionally a preflight/evidence collector rather than a fake
pass generator. A PASS requires the real host to demonstrate WPA_COMPLETED and
network reachability. It never invents live results when the privileged lab is
missing.
"""
from __future__ import annotations
import os,shutil,subprocess,sys,time

def run(cmd,timeout=15):
    try:return subprocess.run(cmd,text=True,capture_output=True,timeout=timeout,check=False)
    except Exception as e:return None

def main():
    required=['ip','iw','wpa_supplicant','wpa_cli']
    tools={x:bool(shutil.which(x)) for x in required}
    root=(os.geteuid()==0); radio=run(['iw','dev']); interfaces=radio.stdout if radio else ''
    print('NETFORGE ENTERPRISE 802.1X PREFLIGHT')
    print('root:',root); print('tools:',tools); print('interfaces_detected:',bool(interfaces.strip()))
    if not root or not all(tools.values()) or not interfaces.strip():
        print('RESULT: BLOCKED — privileged Tier-1 Linux Wi-Fi environment is not ready.')
        return 2
    iface=os.getenv('NETFORGE_WIFI_IFACE','').strip()
    ssid=os.getenv('NETFORGE_ENTERPRISE_SSID','').strip()
    identity=os.getenv('NETFORGE_8021X_IDENTITY','').strip()
    password=os.getenv('NETFORGE_8021X_PASSWORD','')
    if not all([iface,ssid,identity,password]):
        print('RESULT: BLOCKED — set NETFORGE_WIFI_IFACE, NETFORGE_ENTERPRISE_SSID, NETFORGE_8021X_IDENTITY and NETFORGE_8021X_PASSWORD.')
        return 2
    conf=f'''ctrl_interface=/run/wpa_supplicant\nupdate_config=0\nnetwork={{\n ssid="{ssid}"\n key_mgmt=WPA-EAP\n eap=PEAP\n identity="{identity}"\n password="{password}"\n phase2="auth=MSCHAPV2"\n}}\n'''
    path='/tmp/netforge-enterprise-wpa.conf'; open(path,'w',encoding='utf-8').write(conf); os.chmod(path,0o600)
    subprocess.run(['ip','link','set',iface,'up'],check=False)
    proc=subprocess.Popen(['wpa_supplicant','-i',iface,'-c',path,'-dd'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    deadline=time.time()+float(os.getenv('NETFORGE_8021X_TIMEOUT','45')); completed=False; lines=[]
    try:
        while time.time()<deadline:
            line=proc.stdout.readline() if proc.stdout else ''
            if line: lines.append(line.rstrip()); print(line.rstrip())
            if 'CTRL-EVENT-CONNECTED' in line or 'WPA: Key negotiation completed' in line: completed=True; break
            if proc.poll() is not None: break
        ip=run(['ip','addr','show','dev',iface]); reachable=bool(ip and 'inet ' in ip.stdout)
        if completed and reachable:
            print('RESULT: PASS — WPA completion and IP acquisition observed.')
            return 0
        print('RESULT: FAIL — live authentication did not reach WPA completion + IP acquisition.')
        return 1
    finally:
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill()
        open('artifacts/enterprise-8021x-preflight.log','w',encoding='utf-8').write('\n'.join(lines))

if __name__=='__main__': sys.exit(main())
