# NetRegress — Topology Studio and Configuration Demo Pack

This pack contains representative **fixture files** for trying the native topology import path and the Configuration Profiles workspace. These are software demonstration inputs, not complete runnable emulator projects: they do not include vendor VM images, disks, licenses, startup configurations, or live controller bindings.

## Contents

| File | Intended import route | What to inspect |
|---|---|---|
| `native-projects/NetRegress-Branch-Office.gns3` | Topology Studio → Native import | 4 logical nodes, 3 links, node dimensions and original canvas coordinates |
| `native-projects/NetRegress-CML-Campus.yaml` | Topology Studio → Native import | CML Lab YAML 0.1.0, interface-level links and supported text/rectangle annotations |
| `native-projects/NetRegress-EVE-NG-Branch.unl` | Topology Studio → Native import | EVE-NG lab v1, router/firewall/server nodes, two shared bridge networks |
| `configuration/wifi-lab-schema.json` | Configuration Profiles → Schema registry | Versioned, non-secret Wi-Fi settings schema |
| `configuration/wifi-lab-values.json` | Configuration Profiles → Profile revisions | Non-secret JSON revision values |
| `configuration/wifi-lab-values.yaml` | Configuration Profiles → YAML import | Safe YAML-to-draft revision example |
| `scripts/seed_demo_showcase.py` | Run from a terminal against the local Runner API | Idempotently creates/reuses a demo Organization, Project, Lab, configuration schema/profile/revision/assignment and imports the three native topology fixtures |

## Prepare the local checkout

From the repository root, update main and activate the supported Python environment. The locked requirements already include requests:

```bash
git switch main
git pull --ff-only origin main
source wifi-venv/bin/activate
python -m pip check
```

For a new checkout, follow the main README's Python 3.11+/requirements.lock setup first.

## Before running the demo seed script

1. Install and launch the current NetRegress desktop `.deb`, or run the development launcher from the repository root using `./scripts/start_dashboard.sh`.
2. Complete the one-time Global Owner setup in the browser.
3. Keep the application running. The script uses the local HTTP API; it does not edit SQLite directly.
4. Run the seeder from the repository root after activating the repository virtual environment:

```bash
source wifi-venv/bin/activate
python scripts/seed_demo_showcase.py --api-base http://127.0.0.1:5050/api/v1
```

Enter the Global Owner username and password when prompted. The password is read with terminal echo disabled and is not saved. The seeder accepts only an explicit loopback IP, disables environment proxies, and forwards the packaged app's Secure session cookie only to that loopback API.

For the development launcher, the default API port is 5050. For the installed Debian desktop application, Tauri chooses a free port. Locate its backend log and extract the actual port (select the log belonging to the running desktop session):

```bash
find "${XDG_DATA_HOME:-$HOME/.local/share}" -type f -name backend.log -print 2>/dev/null
BACKEND_LOG="/path/to/the/running/netregress/backend.log"
API_PORT="$(grep -Eo 'http://127\.0\.0\.1:[0-9]+' "$BACKEND_LOG" | tail -n 1 | sed 's/.*://')"
test -n "$API_PORT" && printf 'NetRegress API port: %s\n' "$API_PORT"
python scripts/seed_demo_showcase.py --api-base "http://127.0.0.1:$API_PORT/api/v1"
```

The seed script is repeatable: it looks up existing resources by the demo slugs/names and reuses them. It creates only design/workspace/configuration records and imports the native source files. It does **not** create fake Runs, successful deployments, provider health, device observations, telemetry, throughput measurements, packet captures, regression passes, or evidence. The Lab's `gns3` provider identifier is only a workspace label; no GNS3 controller binding is created and the dashboard should continue to show provider health as unknown/unbound.

## Manual import walkthrough

After seeding, sign in to NetRegress and select the `NetRegress Demo` Organization, `Network Engineering Showcase` Project and `Topology Demo Lab` Lab.

For each file in `native-projects/`:

1. Open **Topology Studio**.
2. Choose the project context and select **Import native project**.
3. Choose a clear profile name, set the scope to the demo Lab (or Project if the UI requires that for your test), select the matching source file, and import.
4. Inspect node labels, counts, interface names, link endpoints and native placement. The importer creates a new draft topology revision and retains immutable source provenance.
5. Validate the draft. Publish only when you intend to retain it as a published design revision.
6. Inspect Native Sources / Operations / Reconciliation tabs. Do not click provider apply unless a real provider controller is configured, its credentials are stored in the OS vault, and you explicitly intend to provision resources.

### Expected representation boundaries

- **GNS3:** the supported codec reads GNS3 project JSON revisions 7/8/9 (versions 2.0/2.1/2.2). This fixture targets revision 9 / version 2.2. The shared serializer supports the documented identity-preserving placement/label edit subset; it does not provision images or apply startup configurations.
- **CML:** the supported YAML codec covers Lab schema 0.1.x. This fixture targets 0.1.0. VM Maestro reopening is a separate external check.
- **EVE-NG:** the supported `.unl` codec accepts versions 1 and 2. The fixture models bridge/shared-network segments. EVE Community/Professional controller acceptance and image availability are separate.
- **Packet Tracer:** no synthetic `.pkt` is supplied. A valid `.pkt` must be produced by a real Cisco Packet Tracer installation and tested with the version-specific external reopen workflow. JSON or another format must not be renamed to `.pkt`.

## Configuration Profiles walkthrough

After seeding:

1. Open **Configuration → Configuration profiles**.
2. Confirm the `demo.wifi-lab.v1` schema appears under Schema registry.
3. Select `Demo Wi-Fi Lab Defaults` under Profile revisions.
4. Inspect the immutable revision values (`ssid=NetRegress-Demo`, `channel=36`, `country=IN`) and the published state.
5. Inspect the Configuration assignments table and the effective configuration resolver for the demo Lab.
6. Try importing `configuration/wifi-lab-values.yaml` into a separate draft profile if you want to exercise the safe YAML import flow.

No real device deployment is attempted. To test deployment, use a supported OpenWrt router with an explicitly registered Device, an active same-device SSH credential and Wi-Fi PSK credential in the OS credential vault, then review and explicitly confirm the read-only deployment plan.

## Clean-up

The demo data uses distinct `demo-*` slugs/profile names. Remove it through the application workspace/profile controls only after confirming it is not being used by another demonstration. Do not delete the database or runtime directories to remove demo data.