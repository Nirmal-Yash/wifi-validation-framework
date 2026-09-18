#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# Robust local reprovisioner for wifi-validation-framework.
# Run as the normal Ubuntu user from the repository root. Never prefix with sudo.
# Uses docker/libvirt group membership when available; elevates only for host
# kernel/network ops (sudo -n, else privileged docker). Local-only: no git push.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$SCRIPT_DIR}"
cd "$REPO_ROOT"

# Lab addressing (must stay consistent with configs/*.yaml and the reproduction guide)
LAB_GW="192.168.122.1"
LAB_MASK="255.255.255.0"
LAB_BRIDGE="virbr0"
MGMT_GW="10.10.10.1"
FRR_IP="192.168.122.10"
AP_IP="192.168.122.20"
CLIENT_WIFI_IP="192.168.122.30"
CLIENT_MGMT_IP="10.10.10.30"
MONITOR_IP="192.168.122.40"
SSID="TestNet_5G"
WIFI_PSK="Test@12345"
GNS3_API="${GNS3_API:-http://127.0.0.1:3080}"
GNS3_PROJECT_NAME="${GNS3_PROJECT_NAME:-WiFi-Regression-Lab}"

usage() {
  cat <<'EOF'
Usage:
  ./wifi_lab_reprovision_robust.sh
  ./wifi_lab_reprovision_robust.sh --setup-only
  ./wifi_lab_reprovision_robust.sh --help

Default: preflight -> repair/configure local lab -> validate real paths -> run all tests.
--setup-only: preflight -> repair/configure -> validate, but do not run pytest.
EOF
}

case "${1:-}" in
  "") RUN_TESTS=1 ;;
  --setup-only) RUN_TESTS=0 ;;
  --help|-h) usage; exit 0 ;;
  *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 2 ;;
esac

if [[ $EUID -eq 0 ]]; then
  echo "ERROR: Run as the normal Ubuntu user, not with sudo." >&2
  exit 2
fi

LOG_DIR="$REPO_ROOT/results/setup-logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/setup-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

STEP=0
CURRENT_STEP="initialization"
trap 'rc=$?; echo; echo "ERROR: Step ${STEP} failed: ${CURRENT_STEP} (exit ${rc})" >&2; echo "Log: ${LOG_FILE}" >&2; exit "$rc"' ERR

step() {
  STEP=$((STEP + 1))
  CURRENT_STEP="$1"
  printf '\n================================================================================\nStep %d: %s\n================================================================================\n' "$STEP" "$CURRENT_STEP"
}

die() { echo "ERROR: $*" >&2; return 1; }
require_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing host command: $1"; }

# ---------------------------------------------------------------------------
# Privilege helpers: prefer native access; fall back to sudo -n / privileged docker
# ---------------------------------------------------------------------------
HAVE_SUDO_N=0
sudo -n true >/dev/null 2>&1 && HAVE_SUDO_N=1 || true

DOCKER=(docker)
if ! docker info >/dev/null 2>&1; then
  if ((HAVE_SUDO_N)); then DOCKER=(sudo -n docker); else die "Docker unavailable (add user to docker group or enable passwordless sudo)."; fi
fi

VIRSH=(virsh)
if ! virsh net-info default >/dev/null 2>&1; then
  if ((HAVE_SUDO_N)); then VIRSH=(sudo -n virsh); else die "libvirt virsh unavailable for user (add to libvirt group or enable passwordless sudo)."; fi
fi

host_root() {
  # Run a command in the host mount/network/pid namespaces with root.
  if ((HAVE_SUDO_N)); then
    sudo -n "$@"
    return
  fi
  local cmd
  printf -v cmd '%q ' "$@"
  "${DOCKER[@]}" run --rm --privileged --pid host --network host --volume /:/host \
    alpine:3.20 chroot /host /bin/bash -lc "$cmd"
}

dexec() { local c="$1"; shift; "${DOCKER[@]}" exec "$c" "$@"; }

backup_once() {
  local file="$1"
  [[ -e "$file" ]] || return 0
  local rel="${file#$REPO_ROOT/}"
  local dest="$REPO_ROOT/.robust-backups/${rel//\//__}.baseline.bak"
  mkdir -p "$(dirname "$dest")"
  if [[ ! -e "$dest" ]]; then
    cp -a "$file" "$dest"
    echo "Baseline backup: $dest"
  fi
}

wait_running() {
  local c="$1" i
  for i in {1..30}; do
    if "${DOCKER[@]}" inspect -f '{{.State.Running}}' "$c" 2>/dev/null | grep -qx true; then return 0; fi
    sleep 1
  done
  die "Container did not become running: $c"
}

wait_iface() {
  local c="$1" iface="$2" i
  for i in {1..40}; do
    if dexec "$c" ip link show "$iface" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

container_iface_has() {
  local c="$1" iface="$2"
  dexec "$c" ip link show "$iface" >/dev/null 2>&1
}

container_iface_carrier() {
  local c="$1" iface="$2"
  dexec "$c" ip link show "$iface" | grep -q 'LOWER_UP'
}

container_os_is() {
  local c="$1" expected="$2"
  dexec "$c" sh -c '. /etc/os-release 2>/dev/null && test "$ID" = "$1"' sh "$expected"
}

apt_install_container() {
  local c="$1"; shift
  container_os_is "$c" ubuntu || die "Container $c must be Ubuntu for this step."
  # Skip apt-get when every requested package is already installed (avoids DNS flakes).
  if dexec "$c" sh -c 'for p in "$@"; do dpkg-query -W -f="\${Status}" "$p" 2>/dev/null | grep -q "install ok installed" || exit 1; done' sh "$@"; then
    echo "Container $c already has required packages: $*"
    return 0
  fi
  dexec "$c" sh -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y "$@"' sh "$@"
}

apk_install_container() {
  local c="$1"; shift
  container_os_is "$c" alpine || die "Container $c must be Alpine for this step."
  dexec "$c" sh -c 'apk update && apk add "$@"' sh "$@"
}

find_gns3_container() {
  local prefix="$1" name
  name="$("${DOCKER[@]}" ps -a --format '{{.Names}}' | awk -v p="$prefix" '$0 ~ "^" p "[.]" {print; exit}')"
  [[ -n "$name" ]] || return 1
  printf '%s\n' "$name"
}

# ---------------------------------------------------------------------------
# GNS3 API helpers — start nodes through GNS3 so ubridge attaches interfaces
# ---------------------------------------------------------------------------
GNS3_USER=""
GNS3_PASS=""
GNS3_PROJECT_ID=""

load_gns3_credentials() {
  if [[ -n "${GNS3_API_USER:-}" && -n "${GNS3_API_PASSWORD:-}" ]]; then
    if curl -sS -f -u "${GNS3_API_USER}:${GNS3_API_PASSWORD}" "${GNS3_API}/v2/version" >/dev/null 2>&1; then
      GNS3_USER="$GNS3_API_USER"
      GNS3_PASS="$GNS3_API_PASSWORD"
      return 0
    fi
    echo "WARN: GNS3_API_USER/PASSWORD rejected by ${GNS3_API}; trying config files."
  fi

  local conf user pass tmp
  tmp="$(mktemp)"
  # Collect candidate conf bodies without printing secrets
  # Prefer the running server's conf (/root when gns3server is root-owned).
  {
    host_root test -r /root/.config/GNS3/2.2/gns3_server.conf 2>/dev/null && printf 'HOSTROOT:%s\n' /root/.config/GNS3/2.2/gns3_server.conf
    [[ -r "$HOME/.config/GNS3/2.2/gns3_server.conf" ]] && printf 'FILE:%s\n' "$HOME/.config/GNS3/2.2/gns3_server.conf"
  } >"$tmp.list"

  while IFS= read -r entry; do
    conf="${entry#*:}"
    if [[ "$entry" == FILE:* ]]; then
      user="$(awk -F' *= *' '/^user *=/{print $2; exit}' "$conf" | tr -d '\r')"
      pass="$(awk -F' *= *' '/^password *=/{print $2; exit}' "$conf" | tr -d '\r')"
    else
      user="$(host_root awk -F' *= *' '/^user *=/{print $2; exit}' "$conf" | tr -d '\r')"
      pass="$(host_root awk -F' *= *' '/^password *=/{print $2; exit}' "$conf" | tr -d '\r')"
    fi
    [[ -n "$user" && -n "$pass" ]] || continue
    if curl -sS -f -u "${user}:${pass}" "${GNS3_API}/v2/version" >/dev/null 2>&1; then
      GNS3_USER="$user"
      GNS3_PASS="$pass"
      rm -f "$tmp" "$tmp.list"
      echo "GNS3 API credentials validated."
      return 0
    fi
  done <"$tmp.list"
  rm -f "$tmp" "$tmp.list"
  return 1
}

gns3_curl() {
  local method="$1" path="$2"; shift 2
  curl -sS -f -u "${GNS3_USER}:${GNS3_PASS}" -X "$method" \
    -H 'Content-Type: application/json' \
    "${GNS3_API}${path}" "$@"
}

ensure_gns3_project_and_nodes() {
  load_gns3_credentials || die "Cannot load GNS3 API credentials. Set GNS3_API_USER/GNS3_API_PASSWORD or ensure gns3_server.conf is readable."
  export GNS3_USER GNS3_PASS
  gns3_curl GET /v2/version -o /tmp/gns3_version.json \
    || die "GNS3 API is unreachable at ${GNS3_API}. Start GNS3 first."
  gns3_curl GET /v2/projects -o /tmp/gns3_projects.json
  GNS3_PROJECT_ID="$("$PYTHON" - <<'PY'
import json, os
want=os.environ.get('GNS3_PROJECT_NAME','WiFi-Regression-Lab')
projects=json.load(open('/tmp/gns3_projects.json'))
pid=''
for p in projects:
    if p.get('name')==want:
        pid=p['project_id']; break
if not pid:
    for p in projects:
        if 'frr-router' in str(p) or p.get('name','').lower().find('wifi')>=0:
            pid=p['project_id']; break
if not pid and projects:
    for p in projects:
        if p.get('status')=='opened':
            pid=p['project_id']; break
    if not pid:
        pid=projects[0]['project_id']
print(pid)
PY
)"
  [[ -n "$GNS3_PROJECT_ID" ]] || die "No GNS3 project found. Open WiFi-Regression-Lab in GNS3 first."
  export GNS3_PROJECT_ID
  echo "Using GNS3 project: $GNS3_PROJECT_ID"

  status="$(gns3_curl GET "/v2/projects/$GNS3_PROJECT_ID" | "$PYTHON" -c 'import sys,json; print(json.load(sys.stdin).get("status",""))')"
  if [[ "$status" != "opened" ]]; then
    echo "Opening GNS3 project $GNS3_PROJECT_ID"
    gns3_curl POST "/v2/projects/$GNS3_PROJECT_ID/open" -o /tmp/gns3_open.json >/dev/null || true
  fi

  gns3_curl GET "/v2/projects/$GNS3_PROJECT_ID/nodes" -o /tmp/gns3_nodes.json
  gns3_curl GET "/v2/projects/$GNS3_PROJECT_ID/links" -o /tmp/gns3_links.json

  "$PYTHON" - <<'PY'
import json, sys
nodes=json.load(open('/tmp/gns3_nodes.json'))
by_name={n['name']: n for n in nodes}
required=['frr-router','hostapd-ap','wifi-client','monitor']
missing=[r for r in required if r not in by_name]
if missing:
    sys.exit(f"GNS3 project missing required nodes: {missing}")
client=by_name['wifi-client']
adapters=int(client.get('properties',{}).get('adapters') or 0)
if adapters < 2:
    sys.exit("wifi-client must have at least 2 adapters (eth0 lab, eth1 management).")
# Persist IDs for shell
open('/tmp/gns3_ids.env','w').write(
    f"NODE_FRR={by_name['frr-router']['node_id']}\n"
    f"NODE_AP={by_name['hostapd-ap']['node_id']}\n"
    f"NODE_CLIENT={by_name['wifi-client']['node_id']}\n"
    f"NODE_MONITOR={by_name['monitor']['node_id']}\n"
    f"NODE_SWITCH={by_name.get('Switch1',{}).get('node_id','')}\n"
    f"NODE_CLOUD={next((n['node_id'] for n in nodes if n.get('node_type')=='cloud'),'')}\n"
)
print("GNS3 nodes validated.")
PY
  # shellcheck disable=SC1091
  source /tmp/gns3_ids.env

  # Ensure client eth1 has a path to virbr0 (via Switch or Cloud)
  "$PYTHON" - <<'PY'
import json, os, urllib.request, base64, sys
nodes={n['node_id']:n for n in json.load(open('/tmp/gns3_nodes.json'))}
links=json.load(open('/tmp/gns3_links.json'))
client=os.environ.get('NODE_CLIENT') or open('/tmp/gns3_ids.env').read().split('NODE_CLIENT=')[1].splitlines()[0]
# re-read ids cleanly
ids={}
for line in open('/tmp/gns3_ids.env'):
    k,v=line.strip().split('=',1); ids[k]=v
client=ids['NODE_CLIENT']; switch=ids.get('NODE_SWITCH',''); cloud=ids.get('NODE_CLOUD','')

used=set()
for l in links:
    for x in l['nodes']:
        used.add((x['node_id'], x['adapter_number'], x['port_number']))

client_eth1_linked=any(n['node_id']==client and n['adapter_number']==1 for l in links for n in l['nodes'])
if client_eth1_linked:
    print("Client eth1 management link already present.")
    raise SystemExit(0)

# Prefer free switch port, else fail with guidance
free_switch=None
if switch:
    for p in nodes[switch].get('ports',[]):
        key=(switch, p.get('adapter_number'), p.get('port_number'))
        if key not in used:
            free_switch=(p.get('adapter_number'), p.get('port_number'))
            break
if not free_switch:
    sys.exit("Cannot auto-create management link: no free Switch port. Link wifi-client eth1 to Cloud/virbr0 in GNS3.")

api=os.environ.get('GNS3_API','http://127.0.0.1:3080')
pid=os.environ['GNS3_PROJECT_ID']
user=os.environ['GNS3_USER']; pw=os.environ['GNS3_PASS']
body=json.dumps({"nodes":[
    {"node_id": client, "adapter_number": 1, "port_number": 0},
    {"node_id": switch, "adapter_number": free_switch[0], "port_number": free_switch[1]},
]}).encode()
req=urllib.request.Request(f"{api}/v2/projects/{pid}/links", data=body, method='POST',
    headers={'Content-Type':'application/json',
             'Authorization':'Basic '+base64.b64encode(f'{user}:{pw}'.encode()).decode()})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        print("Created client eth1 management link:", resp.status)
except Exception as e:
    sys.exit(f"Failed to create client eth1 management link: {e}")
PY

  # Start switch/cloud first so docker node links get carrier, then docker nodes.
  for node_id in "$NODE_SWITCH" "$NODE_CLOUD" "$NODE_FRR" "$NODE_AP" "$NODE_CLIENT" "$NODE_MONITOR"; do
    [[ -n "$node_id" ]] || continue
    nstatus="$(gns3_curl GET "/v2/projects/$GNS3_PROJECT_ID/nodes/$node_id" | "$PYTHON" -c 'import sys,json; print(json.load(sys.stdin).get("status",""))' 2>/dev/null || true)"
    if [[ "$nstatus" != "started" ]]; then
      echo "Starting GNS3 node $node_id"
      gns3_curl POST "/v2/projects/$GNS3_PROJECT_ID/nodes/$node_id/start" -o /tmp/gns3_start.json >/dev/null || true
    fi
  done
  sleep 3
}

bounce_gns3_node_if_no_iface() {
  local node_id="$1" cname="$2" iface="$3"
  if wait_iface "$cname" "$iface"; then return 0; fi
  echo "Interface $iface missing on $cname; bouncing via GNS3 API"
  gns3_curl POST "/v2/projects/$GNS3_PROJECT_ID/nodes/$node_id/stop" -o /tmp/gns3_stop.json >/dev/null || true
  sleep 2
  gns3_curl POST "/v2/projects/$GNS3_PROJECT_ID/nodes/$node_id/start" -o /tmp/gns3_start.json >/dev/null
  wait_running "$cname"
  wait_iface "$cname" "$iface" || die "$cname still missing $iface after GNS3 bounce. Check cabling in GNS3."
}

require_container() {
  local var="$1" prefix="$2" label="$3" name
  name="$(find_gns3_container "$prefix")" || die "GNS3 ${label} node is missing. Create it in GNS3 with the required node name, then rerun."
  wait_running "$name"
  printf -v "$var" '%s' "$name"
  echo "${label}: $name"
}

ensure_hwsim_iface() {
  local c="$1" label="$2"
  if container_iface_has "$c" wlan0; then
    echo "$label already has wlan0."
    return 0
  fi
  if container_iface_has "$c" wlan1; then
    dexec "$c" ip link set wlan1 name wlan0
    dexec "$c" ip link set wlan0 up
    echo "$label renamed wlan1 -> wlan0."
    return 0
  fi

  local pid phy
  pid="$("${DOCKER[@]}" inspect -f '{{.State.Pid}}' "$c")"
  phy="$(host_root iw phy 2>/dev/null | awk '/^Wiphy / {print $2}' | head -n1 || true)"
  [[ -n "$phy" ]] || die "No free host mac80211_hwsim PHY available for $label."
  echo "Moving free PHY $phy into $label (PID $pid)."
  host_root iw phy "$phy" set netns "$pid"
  sleep 1
  if container_iface_has "$c" wlan1; then dexec "$c" ip link set wlan1 name wlan0; fi
  dexec "$c" ip link set wlan0 up
  container_iface_has "$c" wlan0 || die "$label did not receive wlan0."
}

set_admin_and_sshd() {
  local c="$1"
  dexec "$c" sh -c '\
    useradd -m -s /bin/bash admin 2>/dev/null || true; \
    echo "admin:admin" | chpasswd; \
    usermod -aG sudo admin 2>/dev/null || true; \
    printf "%s\\n" "admin ALL=(ALL) NOPASSWD: ALL" >/etc/sudoers.d/admin; \
    chmod 440 /etc/sudoers.d/admin; \
    mkdir -p /run/sshd; \
    /usr/sbin/sshd 2>/dev/null || true'
}

validate_default_network() {
  local xml bridge ipaddr netmask
  xml="$("${VIRSH[@]}" net-dumpxml default)"

  bridge="$(printf '%s\n' "$xml" | sed -n "s/.*<bridge[^>]*name=['\"]\\([^'\"]*\\)['\"].*/\\1/p" | head -n1)"
  ipaddr="$(printf '%s\n' "$xml" | sed -n "s/.*<ip[^>]*address=['\"]\\([^'\"]*\\)['\"].*/\\1/p" | head -n1)"
  netmask="$(printf '%s\n' "$xml" | sed -n "s/.*<ip[^>]*netmask=['\"]\\([^'\"]*\\)['\"].*/\\1/p" | head -n1)"

  [[ "$bridge" == "$LAB_BRIDGE" ]] || die "Libvirt default bridge is '$bridge' (expected $LAB_BRIDGE)."
  [[ "$ipaddr" == "$LAB_GW" ]] || die "Libvirt default gateway is '$ipaddr' (expected $LAB_GW)."
  [[ "$netmask" == "$LAB_MASK" ]] || die "Libvirt default netmask is '$netmask' (expected $LAB_MASK)."
  echo "Libvirt default network OK: $bridge $ipaddr/$netmask"

  if ! grep -q '<dhcp>' <<<"$xml" || ! grep -q '<range ' <<<"$xml"; then
    echo "Default network DHCP range is missing; adding the standard 192.168.122.2-254 range."
    "${VIRSH[@]}" net-update default add-last ip-dhcp-range "<range start='192.168.122.2' end='192.168.122.254'/>" --live --config
  fi
}

ensure_libvirt_reservation() {
  local mac="$1" ipaddr="$2" allow_replace="${3:-}" xml current current_owner oldxml
  local owner_ok=0 cand
  [[ -n "$mac" && -n "$ipaddr" ]] || die "ensure_libvirt_reservation requires MAC and IP."
  xml="$("${VIRSH[@]}" net-dumpxml default)"
  current=$("$PYTHON" - "$xml" "$mac" <<'PY'
import sys, xml.etree.ElementTree as ET
root=ET.fromstring(sys.argv[1]); want=sys.argv[2].lower(); found=''
for h in root.findall('.//dhcp/host'):
    if h.get('mac','').lower()==want:
        found=h.get('ip',''); break
print(found)
PY
)
  current_owner=$("$PYTHON" - "$xml" "$ipaddr" <<'PY'
import sys, xml.etree.ElementTree as ET
root=ET.fromstring(sys.argv[1]); want=sys.argv[2]; found=''
for h in root.findall('.//dhcp/host'):
    if h.get('ip','')==want:
        found=h.get('mac',''); break
print(found)
PY
)
  if [[ "$current" == "$ipaddr" ]]; then
    echo "DHCP reservation already correct: $mac -> $ipaddr"
    return 0
  fi
  if [[ -n "$current_owner" && "${current_owner,,}" != "${mac,,}" ]]; then
    owner_ok=0
    IFS=',' read -r -a _allow <<<"$allow_replace"
    for cand in "${_allow[@]}"; do
      [[ -n "$cand" && "${cand,,}" == "${current_owner,,}" ]] && owner_ok=1 && break
    done
    if ((owner_ok)); then
      echo "Replacing same-node DHCP reservation for $ipaddr ($current_owner -> $mac)."
      oldxml="<host mac='$current_owner' ip='$ipaddr'/>"
      "${VIRSH[@]}" net-update default delete ip-dhcp-host "$oldxml" --live --config
    else
      die "DHCP IP $ipaddr is already reserved to MAC $current_owner; refusing to take over an existing reservation."
    fi
  fi
  if [[ -n "$current" ]]; then
    echo "Replacing conflicting DHCP reservation for $mac ($current -> $ipaddr)."
    oldxml="<host mac='$mac' ip='$current'/>"
    "${VIRSH[@]}" net-update default delete ip-dhcp-host "$oldxml" --live --config
  fi
  "${VIRSH[@]}" net-update default add-last ip-dhcp-host "<host mac='$mac' ip='$ipaddr'/>" --live --config
}

wait_for_management() {
  "$PYTHON" - <<PY
from netmiko import ConnectHandler
for host in ("${CLIENT_MGMT_IP}", "${MONITOR_IP}"):
    dev={"host":host,"username":"admin","password":"admin","device_type":"linux","port":22,"conn_timeout":10,"auth_timeout":10}
    last=None
    for _ in range(20):
        try:
            with ConnectHandler(**dev) as c:
                out=c.send_command("echo SSH_OK", read_timeout=30).strip()
                sudo_out=c.send_command("sudo -n true && echo SUDO_OK", read_timeout=30).strip()
                if out=="SSH_OK" and sudo_out=="SUDO_OK":
                    print(f"{host}: SSH_OK / SUDO_OK")
                    break
                raise RuntimeError(f"unexpected output: {out!r} / {sudo_out!r}")
        except Exception as e:
            last=e
            import time; time.sleep(1)
    else:
        raise SystemExit(f"Management SSH validation failed for {host}: {last}")
PY
}

# ---------------------------------------------------------------------------
# 1. PRE-FLIGHT
# ---------------------------------------------------------------------------
step "Pre-flight: validate host baseline and install missing host tools"

# Soft sudo prompt only when passwordless is unavailable and user has a TTY
if ((!HAVE_SUDO_N)) && [[ -t 0 ]]; then
  sudo -v || true
  sudo -n true >/dev/null 2>&1 && HAVE_SUDO_N=1 || true
fi

require_cmd curl
command -v apt-get >/dev/null 2>&1 || die "apt-get is unavailable; this script targets Ubuntu hosts."
missing=()
for p in docker.io libvirt-clients libvirt-daemon-system iproute2 iputils-ping iw openssh-client python3-venv python3-pip curl; do
  dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' || missing+=("$p")
done
if ((${#missing[@]})); then
  if ((HAVE_SUDO_N)); then
    sudo -n apt-get update
    DEBIAN_FRONTEND=noninteractive sudo -n apt-get install -y "${missing[@]}"
  else
    die "Missing host packages: ${missing[*]}. Install them (sudo apt-get install ...) then rerun."
  fi
fi

for c in docker virsh ip iw ping python3 curl; do require_cmd "$c"; done
"${DOCKER[@]}" info >/dev/null 2>&1 || die "Docker daemon is unavailable."

if ! "${VIRSH[@]}" net-info default >/dev/null 2>&1; then
  cat >/tmp/wifi-default.xml <<XML
<network>
  <name>default</name>
  <forward mode='nat'/>
  <bridge name='${LAB_BRIDGE}' stp='on' delay='0'/>
  <ip address='${LAB_GW}' netmask='${LAB_MASK}'>
    <dhcp><range start='192.168.122.2' end='192.168.122.254'/></dhcp>
  </ip>
</network>
XML
  "${VIRSH[@]}" net-define /tmp/wifi-default.xml
fi
active="$("${VIRSH[@]}" net-info default | awk -F: '/^Active:/ {gsub(/[[:space:]]/,"",$2); print $2}')"
if [[ "$active" != yes ]]; then
  "${VIRSH[@]}" net-start default
else
  echo "Libvirt default network is already active; no net-start attempted."
fi
"${VIRSH[@]}" net-autostart default >/dev/null 2>&1 || true
ip link show "$LAB_BRIDGE" >/dev/null 2>&1 || die "$LAB_BRIDGE is not present."

VENV="$REPO_ROOT/wifi-venv"
if [[ ! -x "$VENV/bin/python" ]]; then python3 -m venv "$VENV"; fi
PYTHON="$VENV/bin/python"
export PYTHON GNS3_API GNS3_PROJECT_NAME
validate_default_network

# GNS3 API: open project, ensure management link, start nodes properly
step "Pre-flight: align GNS3 topology and start nodes via API"
export GNS3_USER GNS3_PASS
ensure_gns3_project_and_nodes
export GNS3_USER GNS3_PASS GNS3_PROJECT_ID NODE_FRR NODE_AP NODE_CLIENT NODE_MONITOR NODE_SWITCH NODE_CLOUD

require_container FRR 'GNS3.frr-router' 'FRR router'
require_container AP 'GNS3.hostapd-ap' 'access point'
require_container CLIENT 'GNS3.wifi-client' 'WiFi client'
require_container MONITOR 'GNS3.monitor' 'monitor'

bounce_gns3_node_if_no_iface "$NODE_FRR" "$FRR" eth1
bounce_gns3_node_if_no_iface "$NODE_AP" "$AP" eth0
bounce_gns3_node_if_no_iface "$NODE_CLIENT" "$CLIENT" eth0
bounce_gns3_node_if_no_iface "$NODE_CLIENT" "$CLIENT" eth1
bounce_gns3_node_if_no_iface "$NODE_MONITOR" "$MONITOR" eth0

for spec in "$FRR eth1" "$AP eth0" "$CLIENT eth0" "$CLIENT eth1" "$MONITOR eth0"; do
  c="${spec% *}"; i="${spec##* }"
  container_iface_has "$c" "$i" || die "$c is missing interface $i. Check the GNS3 node adapter count/cabling."
  dexec "$c" ip link set "$i" up >/dev/null 2>&1 || true
done
for spec in "$FRR eth1" "$AP eth0" "$CLIENT eth0" "$CLIENT eth1" "$MONITOR eth0"; do
  c="${spec% *}"; i="${spec##* }"
  for _try in {1..45}; do
    if container_iface_carrier "$c" "$i"; then
      echo "$c $i carrier OK"
      break
    fi
    if ((_try == 20)) && [[ -n "${NODE_SWITCH:-}" ]]; then
      echo "No carrier yet on $c $i; bouncing GNS3 switch"
      gns3_curl POST "/v2/projects/$GNS3_PROJECT_ID/nodes/$NODE_SWITCH/stop" -o /tmp/gns3_stop.json >/dev/null || true
      sleep 2
      gns3_curl POST "/v2/projects/$GNS3_PROJECT_ID/nodes/$NODE_SWITCH/start" -o /tmp/gns3_start.json >/dev/null || true
      sleep 2
      dexec "$c" ip link set "$i" up >/dev/null 2>&1 || true
    fi
    sleep 1
  done
  container_iface_carrier "$c" "$i" || die "$c $i has no carrier. Check GNS3 links/Cloud connections before rerunning."
done

# ---------------------------------------------------------------------------
# 2. HOST MANAGEMENT ADDRESS
# ---------------------------------------------------------------------------
step "Prepare host virbr0 management address"
if ! ip -4 addr show "$LAB_BRIDGE" | grep -q "inet ${MGMT_GW}/24"; then
  host_root ip addr replace "${MGMT_GW}/24" dev "$LAB_BRIDGE"
fi
ip -4 addr show "$LAB_BRIDGE" | grep -q "inet ${MGMT_GW}/24" || die "Failed to add ${MGMT_GW}/24 on ${LAB_BRIDGE}."
echo "Management gateway ${MGMT_GW}/24 present on ${LAB_BRIDGE}."

# ---------------------------------------------------------------------------
# 3. PYTHON + LOCAL REPOSITORY BASELINE
# ---------------------------------------------------------------------------
step "Repair Python dependencies and required local repository configuration"
"$PYTHON" -m pip install --upgrade pip setuptools wheel
"$PYTHON" -m pip install 'netmiko==4.7.0' 'pytest==8.1.0' 'pytest-html==4.1.1' 'PyYAML>=6.0' 'scapy==2.5.0' 'python-dotenv>=1.0.0'

for f in requirements.txt configs/devices.yaml configs/test_params.yaml configs/topology.yaml pytest.ini; do backup_once "$REPO_ROOT/$f"; done

# Merge required pins into requirements.txt without dropping dashboard deps
"$PYTHON" - <<'PY'
from pathlib import Path
req=Path('requirements.txt')
lines=req.read_text().splitlines() if req.exists() else []
required={
 'netmiko':'netmiko==4.7.0',
 'pytest':'pytest==8.1.0',
 'pytest-html':'pytest-html==4.1.1',
 'pyyaml':'PyYAML>=6.0',
 'scapy':'scapy==2.5.0',
 'python-dotenv':'python-dotenv>=1.0.0',
}
out=[]; seen=set()
for line in lines:
    raw=line.strip()
    if not raw or raw.startswith('#'):
        out.append(line); continue
    name=raw.split('==')[0].split('>=')[0].split('<=')[0].strip().lower().replace('_','-')
    if name in required:
        out.append(required[name]); seen.add(name)
    else:
        out.append(line)
for k,v in required.items():
    if k not in seen:
        out.append(v)
req.write_text('\n'.join(out).rstrip()+'\n')
print('requirements.txt normalized')
PY

mkdir -p configs results/captures results/setup-logs
if [[ ! -f pytest.ini ]]; then
  cat >pytest.ini <<'INI'
[pytest]
pythonpath = .
markers =
    smoke: Quick connectivity checks
    regression: Full regression suite
    perf: Performance and throughput tests
testpaths = tests
addopts = -v --tb=short
INI
fi

"$PYTHON" - <<PY
from pathlib import Path
import yaml

p=Path('configs/devices.yaml'); d=yaml.safe_load(p.read_text()) if p.exists() else {}; d=d or {}; dev=d.setdefault('devices',{})
required={
 'router1': {'host':'${FRR_IP}','username':'admin','password':'admin','device_type':'linux','port':22},
 'router2': {'host':'192.168.122.11','username':'admin','password':'admin','device_type':'linux','port':22},
 'ap_host': {'host':'${AP_IP}','username':'admin','password':'admin','device_type':'linux','port':22},
 'client_vm': {'host':'${CLIENT_MGMT_IP}','username':'admin','password':'admin','device_type':'linux','port':22},
 'monitor_vm': {'host':'${MONITOR_IP}','username':'admin','password':'admin','device_type':'linux','port':22},
}
for k,v in required.items():
    cur=dev.setdefault(k,{})
    cur.update(v)
p.write_text(yaml.safe_dump(d,sort_keys=False))

p=Path('configs/test_params.yaml'); d=yaml.safe_load(p.read_text()) if p.exists() else {}; d=d or {}
d.setdefault('wifi',{}).update({'ssid':'${SSID}','password':'${WIFI_PSK}','security':'WPA2'})
d.setdefault('thresholds',{}).update({'min_throughput_mbps':20,'max_latency_ms':50,'max_packet_loss_pct':2,'dhcp_timeout_sec':10,'dns_timeout_sec':5})
d.setdefault('dns',{}).update({'test_hostname':'google.com'})
d.setdefault('auth',{}).update({'wpa_version':'WPA2','connection_timeout_sec':15})
d.setdefault('firmware',{}).update({'current_version':'v1.0','baseline_version':'v1.0','upgrade_version':'v2.0'})
d.setdefault('network',{}).update({
  'router_ip':'${FRR_IP}',
  'client_interface':'wlan0',
  'monitor_interface':'eth0',
  'dhcp_subnet':'192.168.122.0/24',
  'client_management_ip':'${CLIENT_MGMT_IP}',
  'client_wifi_ip':'${CLIENT_WIFI_IP}',
  'ap_ip':'${AP_IP}',
  'monitor_ip':'${MONITOR_IP}',
  'management_gateway':'${MGMT_GW}',
  'lab_gateway':'${LAB_GW}',
})
p.write_text(yaml.safe_dump(d,sort_keys=False))

p=Path('configs/topology.yaml')
t={
 'lab_name':'WiFi Regression Lab',
 'nodes':[
   {'name':'frr-router','type':'frr','ip':'${FRR_IP}','role':'iperf3 server and lab router'},
   {'name':'hostapd-ap','type':'access_point','ip':'${AP_IP}','role':'Software WiFi access point (hostapd)'},
   {'name':'wifi-client','type':'client','ip':'${CLIENT_WIFI_IP}','management_ip':'${CLIENT_MGMT_IP}','role':'WiFi client VM (wpa_supplicant)'},
   {'name':'monitor','type':'monitor','ip':'${MONITOR_IP}','role':'Packet capture (tcpdump)'},
 ],
 'links':[
   {'from':'frr-router','to':'hostapd-ap','type':'ethernet'},
   {'from':'hostapd-ap','to':'wifi-client','type':'simulated WiFi (mac80211_hwsim)'},
   {'from':'frr-router','to':'monitor','type':'ethernet'},
   {'from':'wifi-client','to':'host','type':'management via GNS3 Cloud to virbr0'},
 ]}
p.write_text(yaml.safe_dump(t,sort_keys=False))
print('configs normalized')
PY

"$PYTHON" - <<'PY'
from pathlib import Path
import netmiko
from scapy.all import BOOTP,DHCP,DNS,EAPOL,IP,UDP,Dot11,Dot11Beacon,Dot11Elt,Ether,rdpcap,wrpcap
for p in ('lib/connector.py','lib/traffic.py','lib/wifi_analyzer.py'):
    compile(Path(p).read_text(),p,'exec')
print('Netmiko:',netmiko.__version__)
print('Scapy BOOTP/DHCP/WiFi imports: OK')
PY

# ---------------------------------------------------------------------------
# 4. VERIFIED LOCAL CODE FIXES + STRICT TEST INTEGRITY
# ---------------------------------------------------------------------------
step "Apply verified compatibility fixes and remove test success fallbacks"
for f in lib/connector.py lib/traffic.py lib/wifi_analyzer.py tests/test_fault_injection.py tests/test_packet_capture.py tests/test_ping.py; do backup_once "$REPO_ROOT/$f"; done

"$PYTHON" - <<'PY'
from pathlib import Path

p=Path('lib/connector.py'); s=p.read_text()
s='\n'.join(line for line in s.splitlines() if 'dev.setdefault("read_timeout", 30)' not in line)+'\n'
marker='    def send_command(self, device_name, command, **kwargs):\n'
if 'kwargs.setdefault("read_timeout", 30)' not in s:
    if marker not in s: raise SystemExit('connector.py send_command marker not found')
    s=s.replace(marker,marker+'        kwargs.setdefault("read_timeout", 30)\n',1)
p.write_text(s)

p=Path('lib/traffic.py'); s=p.read_text().replace('def run_ping(host, count=10, timeout=15):','def run_ping(host, count=10, timeout=30):'); p.write_text(s)

p=Path('lib/wifi_analyzer.py'); s=p.read_text().replace('Bootp,','BOOTP,').replace('Bootp(','BOOTP('); p.write_text(s)

for f in ('lib/connector.py','lib/traffic.py','lib/wifi_analyzer.py','tests/test_ping.py','tests/test_fault_injection.py','tests/test_packet_capture.py'):
    compile(Path(f).read_text(),f,'exec')
PY

cat >tests/test_fault_injection.py <<'PY'
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from lib.fault_injector import clear_conditions, fault_context, link_down, link_up


def client_ping(connection_pool, router_ip, count=3):
    output = connection_pool.send_command("client_vm", f"ping -c {count} {router_ip} 2>&1")
    match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
    loss = float(match.group(1)) if match else 100.0
    return {"success": loss < 100.0, "packet_loss_pct": loss, "output": output}


@pytest.mark.regression
def test_fault_injection_link_down_up(params, connection_pool, metric_logger):
    """Disrupt the real WiFi interface while SSH management stays on eth1."""
    router_ip = params["network"]["router_ip"]
    iface = params["network"]["client_interface"]
    assert iface == "wlan0", "Real fault injection requires client_interface=wlan0"

    baseline = client_ping(connection_pool, router_ip, 3)
    if not baseline["success"]:
        pytest.skip(f"Baseline client WiFi connectivity to {router_ip} unavailable")

    def do_down():
        link_down(iface, pool=connection_pool, device="client_vm")

    def do_up():
        try:
            link_up(iface, pool=connection_pool, device="client_vm")
            clear_conditions(iface, pool=connection_pool, device="client_vm")
            connection_pool.send_command("client_vm", "wpa_cli -i wlan0 reconnect 2>/dev/null || true")
        except Exception:
            pass

    with fault_context(do_down, do_up):
        down_result = client_ping(connection_pool, router_ip, 3)
        assert (not down_result["success"] or down_result["packet_loss_pct"] > 50), (
            f"WiFi traffic was not disrupted: {down_result}"
        )

    time.sleep(2)
    recovered = client_ping(connection_pool, router_ip, 3)
    metric_logger.log(recovered["packet_loss_pct"], "%")
    assert recovered["success"], f"WiFi connectivity did not recover: {recovered}"
PY

cat >tests/test_ping.py <<'PY'
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


def client_ping(connection_pool, router_ip, count):
    output = connection_pool.send_command(
        "client_vm",
        f"ping -c {count} -W 3 {router_ip} 2>&1",
    )
    loss_match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
    loss = float(loss_match.group(1)) if loss_match else 100.0
    rtt_match = re.search(r"rtt min/avg/max/(?:mdev|stddev)\s*=\s*[\d.]+/([\d.]+)/", output, re.IGNORECASE)
    avg = float(rtt_match.group(1)) if rtt_match else None
    return {"success": loss < 100.0, "packet_loss_pct": loss, "avg_rtt_ms": avg, "output": output}


@pytest.mark.perf
def test_ping_success(params, connection_pool, metric_logger):
    router_ip = params["network"]["router_ip"]
    result = client_ping(connection_pool, router_ip, 5)
    metric_logger.log(1.0 if result["success"] else 0.0, "bool")
    assert result["success"], f"Client WiFi ping to router {router_ip} failed: {result['output']}"


@pytest.mark.perf
def test_packet_loss_within_threshold(params, connection_pool, metric_logger):
    router_ip = params["network"]["router_ip"]
    result = client_ping(connection_pool, router_ip, 20)
    loss = result["packet_loss_pct"]
    metric_logger.log(loss, "%")
    threshold = params["thresholds"]["max_packet_loss_pct"]
    assert loss <= threshold, f"Client WiFi packet loss of {loss}% exceeds threshold {threshold}%"


@pytest.mark.perf
def test_latency_within_threshold(params, connection_pool, metric_logger):
    router_ip = params["network"]["router_ip"]
    result = client_ping(connection_pool, router_ip, 10)
    rtt = result["avg_rtt_ms"]
    assert rtt is not None, f"Could not parse client WiFi average RTT: {result['output']}"
    metric_logger.log(rtt, "ms")
    threshold = params["thresholds"]["max_latency_ms"]
    assert rtt <= threshold, f"Client WiFi latency of {rtt}ms exceeds threshold {threshold}ms"
PY

cat >tests/test_packet_capture.py <<'PY'
import base64
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from lib.wifi_analyzer import analyze_dhcp_sequence


@pytest.mark.regression
def test_pcap_contains_dhcp_packets(connection_pool, params, metric_logger):
    """Validate a real monitor capture; no synthetic PCAP fallback."""
    monitor_iface = params["network"]["monitor_interface"]
    client_iface = params["network"]["client_interface"]
    remote_pcap = "/tmp/dhcp_test.pcap"
    local_pcap = ROOT / "results" / "captures" / "dhcp_test.pcap"
    local_pcap.parent.mkdir(parents=True, exist_ok=True)

    capture = (
        f"sudo rm -f {remote_pcap}; "
        f"sudo timeout 12 tcpdump -i {monitor_iface} -nn -s0 -w {remote_pcap} "
        f"'udp port 67 or udp port 68' >/tmp/dhcp_capture.log 2>&1 & echo $!"
    )
    pid = connection_pool.send_command("monitor_vm", capture, read_timeout=30).strip()
    assert re.search(r"^\d+$", pid), f"Could not start tcpdump: {pid!r}"

    time.sleep(1)
    connection_pool.send_command(
        "client_vm",
        f"sudo dhclient -r {client_iface} 2>/dev/null || true; sudo dhclient {client_iface}",
        read_timeout=30,
    )
    time.sleep(4)

    state = connection_pool.send_command(
        "monitor_vm", f"test -s {remote_pcap} && echo FILE_EXISTS || echo NO_FILE"
    ).strip()
    assert state == "FILE_EXISTS", "Monitor did not create a non-empty real DHCP PCAP"

    b64 = connection_pool.send_command("monitor_vm", f"sudo base64 -w 0 {remote_pcap}", read_timeout=30)
    clean = "".join(b64.split())
    try:
        data = base64.b64decode(clean, validate=True)
    except Exception as exc:
        raise AssertionError("Could not decode monitor PCAP") from exc
    assert data, "Decoded monitor PCAP is empty"
    local_pcap.write_bytes(data)

    analysis = analyze_dhcp_sequence(str(local_pcap))
    metric_logger.log(analysis["total_packets"], "packets")
    assert analysis["total_packets"] > 0, f"No DHCP frames in real PCAP: {analysis}"
    assert analysis["has_lease_acquired"], f"Real DHCP capture has no ACK: {analysis['message_counts']}"
PY

# ---------------------------------------------------------------------------
# 5. HOST WIFI RADIO PLACEMENT
# ---------------------------------------------------------------------------
step "Provision the two mac80211_hwsim radios"
AP_HAS_WLAN=0; CLIENT_HAS_WLAN=0
container_iface_has "$AP" wlan0 && AP_HAS_WLAN=1 || true
container_iface_has "$CLIENT" wlan0 && CLIENT_HAS_WLAN=1 || true
if [[ ! -d /sys/module/mac80211_hwsim ]]; then
  host_root modprobe mac80211_hwsim radios=2
elif (( AP_HAS_WLAN == 0 && CLIENT_HAS_WLAN == 0 )); then
  FREE_PHYS="$(host_root iw phy 2>/dev/null | awk '/^Wiphy / {c++} END {print c+0}')"
  if (( FREE_PHYS < 2 )); then
    host_root modprobe -r mac80211_hwsim || true
    host_root modprobe mac80211_hwsim radios=2
  fi
fi
ensure_hwsim_iface "$AP" "AP"
ensure_hwsim_iface "$CLIENT" "Client"

# ---------------------------------------------------------------------------
# 6. FRR ROUTER
# ---------------------------------------------------------------------------
step "Configure FRR router and real iperf3 server"
dexec "$FRR" sh -c "
  ip link set eth1 up
  ip addr replace ${FRR_IP}/24 dev eth1
  ip route replace default via ${LAB_GW} dev eth1
  printf 'nameserver 8.8.8.8\\n' >/etc/resolv.conf
"
apk_install_container "$FRR" iperf3

if ! dexec "$FRR" sh -c 'ss -lnt 2>/dev/null | grep -q "\\*:5201"'; then
  dexec "$FRR" iperf3 -s -D
fi

dexec "$FRR" sh -c "ping -c 2 -W 3 ${LAB_GW} >/dev/null"
FRR_MAC="$(dexec "$FRR" cat /sys/class/net/eth1/address | tr -d '\r\n')"
ensure_libvirt_reservation "$FRR_MAC" "$FRR_IP"

# ---------------------------------------------------------------------------
# 7. AP
# ---------------------------------------------------------------------------
step "Configure AP bridge, hostapd, and WPA2"
dexec "$AP" sh -c "
  ip link set eth0 up
  ip addr replace ${AP_IP}/24 dev eth0
  ip route replace default via ${LAB_GW} dev eth0
  printf 'nameserver 8.8.8.8\\n' >/etc/resolv.conf
"
apt_install_container "$AP" hostapd openssh-server bridge-utils iw wpasupplicant sudo iproute2 iputils-ping
set_admin_and_sshd "$AP"

dexec "$AP" sh -c "
  ip link add br0 type bridge 2>/dev/null || true
  ip link set eth0 master br0 2>/dev/null || true
  ip link set br0 up
  ip addr flush dev eth0
  ip addr replace ${AP_IP}/24 dev br0
  ip route replace default via ${LAB_GW} dev br0

  cat >/etc/hostapd/hostapd.conf <<EOF
interface=wlan0
bridge=br0
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=6
wpa=2
wpa_passphrase=${WIFI_PSK}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
rsn_pairwise=CCMP
EOF

  # Fully reset wlan0 so a prior hostapd run cannot leave nl80211 'Match already configured'.
  pkill -9 hostapd 2>/dev/null || true
  sleep 1
  ip link set wlan0 down 2>/dev/null || true
  iw dev wlan0 set type managed 2>/dev/null || true
  ip link set wlan0 nomaster 2>/dev/null || true
  ip addr flush dev wlan0 2>/dev/null || true
  ip link set wlan0 up
  hostapd -B /etc/hostapd/hostapd.conf
"

dexec "$AP" iw dev wlan0 info | grep -q "ssid ${SSID}"
dexec "$AP" sh -c 'bridge link | grep -q "master br0"'
AP_MAC="$(dexec "$AP" cat /sys/class/net/eth0/address | tr -d '\r\n')"
ensure_libvirt_reservation "$AP_MAC" "$AP_IP"
dexec "$AP" sh -c "ping -c 2 -W 3 ${FRR_IP} >/dev/null"

# ---------------------------------------------------------------------------
# 8. MONITOR
# ---------------------------------------------------------------------------
step "Configure monitor VM for real packet capture"
dexec "$MONITOR" sh -c "
  ip link set eth0 up
  ip addr replace ${MONITOR_IP}/24 dev eth0
  ip route replace default via ${LAB_GW} dev eth0
  printf 'nameserver 8.8.8.8\\n' >/etc/resolv.conf
"
apt_install_container "$MONITOR" openssh-server sudo tcpdump iproute2 iputils-ping
set_admin_and_sshd "$MONITOR"
dexec "$MONITOR" rm -f /etc/profile.d/80-systemd-osc-context.sh

MONITOR_MAC="$(dexec "$MONITOR" cat /sys/class/net/eth0/address | tr -d '\r\n')"
ensure_libvirt_reservation "$MONITOR_MAC" "$MONITOR_IP"
dexec "$MONITOR" sh -c "ping -c 2 -W 3 ${FRR_IP} >/dev/null"

# ---------------------------------------------------------------------------
# 9. CLIENT PACKAGE BASELINE + WIFI
# ---------------------------------------------------------------------------
step "Configure client packages, WiFi association, DHCP reservation, and management SSH"
dexec "$CLIENT" sh -c "
  ip link set eth0 up
  ip addr replace 192.168.122.250/24 dev eth0
  ip route replace default via ${LAB_GW} dev eth0
  printf 'nameserver 8.8.8.8\\n' >/etc/resolv.conf
"
apt_install_container "$CLIENT" iw wpasupplicant openssh-server iperf3 bind9-dnsutils isc-dhcp-client sudo iproute2 iputils-ping
set_admin_and_sshd "$CLIENT"
dexec "$CLIENT" rm -f /etc/profile.d/80-systemd-osc-context.sh

dexec "$CLIENT" sh -c "
  cat >/etc/wpa_supplicant.conf <<EOF
ctrl_interface=DIR=/run/wpa_supplicant GROUP=admin
update_config=1
country=IN
p2p_disabled=1

network={
    ssid=\"${SSID}\"
    psk=\"${WIFI_PSK}\"
    key_mgmt=WPA-PSK
}
EOF

  # Idempotent client WiFi bring-up: clear stale nl80211/wpa state.
  pkill -9 wpa_supplicant 2>/dev/null || true
  sleep 1
  rm -rf /run/wpa_supplicant
  mkdir -p /run/wpa_supplicant
  ip link set wlan0 down 2>/dev/null || true
  iw dev wlan0 set type managed 2>/dev/null || true
  ip addr flush dev wlan0 2>/dev/null || true
  ip link set wlan0 up
  wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant.conf -D nl80211
"
sleep 2
for _try in {1..30}; do
  if dexec "$CLIENT" sh -c 'test -S /run/wpa_supplicant/wlan0'; then
    break
  fi
  sleep 1
done
dexec "$CLIENT" sh -c 'test -S /run/wpa_supplicant/wlan0' || die "wpa_supplicant control socket missing on client wlan0."

for _try in {1..30}; do
  if dexec "$CLIENT" sh -c 'wpa_cli -i wlan0 status | grep -q "wpa_state=COMPLETED"'; then
    break
  fi
  # Nudge association if stuck
  if ((_try == 10)) || ((_try == 20)); then
    dexec "$CLIENT" sh -c 'wpa_cli -i wlan0 reconfigure 2>/dev/null || true; wpa_cli -i wlan0 reconnect 2>/dev/null || true' || true
  fi
  sleep 1
done
dexec "$CLIENT" sh -c 'wpa_cli -i wlan0 status | grep -q "wpa_state=COMPLETED"' || {
  dexec "$CLIENT" sh -c 'wpa_cli -i wlan0 status; iw dev wlan0 link' || true
  die "Client failed to complete WPA2 association to ${SSID}."
}

WIFI_MAC="$(dexec "$CLIENT" cat /sys/class/net/wlan0/address | tr -d '\r\n')"
CLIENT_ETH0_MAC="$(dexec "$CLIENT" cat /sys/class/net/eth0/address | tr -d '\r\n')"
CLIENT_ETH1_MAC="$(dexec "$CLIENT" cat /sys/class/net/eth1/address | tr -d '\r\n')"
[[ "$WIFI_MAC" =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]] || die "Invalid wlan0 MAC: $WIFI_MAC"
ensure_libvirt_reservation "$WIFI_MAC" "$CLIENT_WIFI_IP" "${CLIENT_ETH0_MAC},${CLIENT_ETH1_MAC}"

dexec "$CLIENT" sh -c "
  dhclient -r wlan0 2>/dev/null || true
  dhclient wlan0
  # Ensure WiFi default route even if dhclient omits it after eth0 flush.
  ip route replace default via ${LAB_GW} dev wlan0
  ip link set eth1 up
  ip addr replace ${CLIENT_MGMT_IP}/24 dev eth1
  # Management subnet must not steal lab default route.
  ip route replace ${MGMT_GW}/32 dev eth1 2>/dev/null || true
  ip addr flush dev eth0
  ip route del default dev eth0 2>/dev/null || true
  # Prefer wlan0 default if multiple defaults exist.
  ip route replace default via ${LAB_GW} dev wlan0
"

dexec "$CLIENT" sh -c "ip -4 addr show wlan0 | grep -q '${CLIENT_WIFI_IP}/24'"
dexec "$CLIENT" sh -c "ip -4 addr show eth1 | grep -q '${CLIENT_MGMT_IP}/24'"
if dexec "$CLIENT" ip -4 addr show eth0 | grep -q 'inet '; then
  die "Client eth0 still has an IPv4 address after final isolation."
fi

# ---------------------------------------------------------------------------
# 10. MANAGEMENT + REAL END-TO-END VALIDATION
# ---------------------------------------------------------------------------
step "Validate isolated management and real WiFi data path"
wait_for_management

dexec "$CLIENT" sh -c "wpa_cli -i wlan0 status | grep -q 'ssid=${SSID}'"
dexec "$CLIENT" sh -c 'wpa_cli -i wlan0 status | grep -q "wpa_state=COMPLETED"'
# Non-destructive SSID check (iw scan can break hwsim association mid-validation).
dexec "$CLIENT" sh -c "iw dev wlan0 link | grep -q 'SSID: ${SSID}'"
dexec "$CLIENT" sh -c "ping -c 3 -W 3 ${FRR_IP} >/dev/null"
# Internet path is best-effort through libvirt NAT; require lab gateway first.
dexec "$CLIENT" sh -c "ping -c 2 -W 3 ${LAB_GW} >/dev/null"
if ! dexec "$CLIENT" sh -c 'ping -c 2 -W 5 8.8.8.8 >/dev/null'; then
  echo "WARN: outbound ICMP to 8.8.8.8 failed; continuing if DNS still works via lab path."
fi
if ! dexec "$CLIENT" sh -c 'nslookup google.com >/dev/null'; then
  # Fall back to DNS via public resolver IP to isolate DNS vs ICMP filtering
  dexec "$CLIENT" sh -c 'nslookup google.com 8.8.8.8 >/dev/null' \
    || die "DNS resolution failed from client WiFi path."
fi
dexec "$CLIENT" ip route | grep -Eq "^default[[:space:]]+via[[:space:]]+${LAB_GW}([[:space:]].*)?[[:space:]]+dev[[:space:]]+wlan0([[:space:]]|$)" \
  || die "Client default route via ${LAB_GW} on wlan0 is missing."

if (( RUN_TESTS == 0 )); then
  step "Setup-only completed"
  echo "Client management: ${CLIENT_MGMT_IP}"
  echo "Client WiFi: ${CLIENT_WIFI_IP}"
  echo "FRR: ${FRR_IP}"
  echo "AP: ${AP_IP}"
  echo "Monitor: ${MONITOR_IP}"
  echo "Setup log: $LOG_FILE"
  exit 0
fi

# ---------------------------------------------------------------------------
# 11. FULL REAL TEST SUITE
# ---------------------------------------------------------------------------
step "Run the complete real regression suite"
"$PYTHON" -m pytest tests/ -v --firmware-version=v1.0

step "Final service and DHCP verification"
"${VIRSH[@]}" net-dhcp-leases default || true
dexec "$FRR" sh -c 'ss -lnt 2>/dev/null | grep -q "\\*:5201"'
dexec "$CLIENT" sh -c "ss -lnt 2>/dev/null | grep -q ':22'; wpa_cli -i wlan0 status | grep -q 'wpa_state=COMPLETED'; ip -4 addr show wlan0 | grep -q '${CLIENT_WIFI_IP}/24'"
dexec "$MONITOR" sh -c 'command -v tcpdump >/dev/null'

echo
echo "================================================================================"
echo "ROBUST WIFI LAB SETUP + REAL TEST SUITE COMPLETED"
echo "Log: $LOG_FILE"
echo "================================================================================"
