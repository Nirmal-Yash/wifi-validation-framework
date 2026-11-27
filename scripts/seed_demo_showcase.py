#!/usr/bin/env python3
"""Seed a small, honest NetRegress workspace and import native topology fixtures.

The script talks to the authenticated Runner API. It never opens SQLite directly,
never stores a password, and deliberately avoids inventing live Runs, metrics,
provider health, device state, telemetry, captures, or deployment outcomes.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import uuid
import ipaddress
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = ROOT / "examples" / "demo-showcase"
SCHEMA = {
    "type": "object",
    "required": ["ssid", "channel"],
    "additionalProperties": False,
    "properties": {
        "ssid": {"type": "string", "minLength": 1, "maxLength": 32},
        "channel": {"type": "integer", "minimum": 1, "maximum": 165},
        "country": {"type": "string", "minLength": 2, "maxLength": 2},
    },
}
VALUES = {"ssid": "NetRegress-Demo", "channel": 36, "country": "IN"}
TOPOLOGIES = (
    ("NetRegress Demo - GNS3 Branch Office", "native-projects/NetRegress-Branch-Office.gns3", "application/json"),
    ("NetRegress Demo - CML Campus", "native-projects/NetRegress-CML-Campus.yaml", "application/yaml"),
    ("NetRegress Demo - EVE-NG Branch", "native-projects/NetRegress-EVE-NG-Branch.unl", "application/xml"),
)


class RunnerAPIError(RuntimeError):
    pass



def validate_loopback_api_base(api_base: str) -> str:
    """Reject non-loopback destinations before sending Global Owner credentials."""
    parsed = urlsplit(api_base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RunnerAPIError("API base must be an HTTP(S) URL on a loopback IP address.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RunnerAPIError("API base must not contain credentials, a query, or a fragment.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
        _ = parsed.port
    except ValueError as exc:
        raise RunnerAPIError("Use an explicit loopback IP such as 127.0.0.1 or ::1; hostnames and remote hosts are not accepted.") from exc
    if not address.is_loopback:
        raise RunnerAPIError("Global Owner credentials may only be sent to a loopback Runner API address.")
    if parsed.path.rstrip("/") != "/api/v1":
        raise RunnerAPIError("API base must include the /api/v1 path.")
    return api_base.rstrip("/") + "/"


def extract_cookie_header(response: requests.Response) -> str:
    """Copy session cookie pairs for the local loopback API.

    The packaged Tauri app sets its local session cookie Secure even though the
    backend listens on loopback HTTP. Requests' default cookie jar will not
    send that cookie over HTTP, so the seeder forwards only name/value pairs
    from the local login response. The API URL is restricted to a loopback IP
    and environment proxies are disabled before this is used.
    """
    raw_headers = getattr(response.raw, "headers", None)
    get_all = getattr(raw_headers, "getlist", None)
    set_cookie_headers = get_all("Set-Cookie") if callable(get_all) else None
    if not set_cookie_headers:
        value = response.headers.get("Set-Cookie")
        set_cookie_headers = [value] if value else []
    parsed = SimpleCookie()
    for value in set_cookie_headers:
        parsed.load(value)
    pairs = [f"{name}={morsel.value}" for name, morsel in parsed.items()]
    if not pairs:
        raise RunnerAPIError("Login succeeded but the loopback API did not return a session cookie.")
    return "; ".join(pairs)


class RunnerClient:
    def __init__(self, api_base: str, username: str, password: str) -> None:
        self.api_base = validate_loopback_api_base(api_base)
        self.session = requests.Session()
        # Do not send local Owner credentials through an environment proxy.
        self.session.trust_env = False
        response = self.session.post(
            urljoin(self.api_base, "auth/login"),
            json={"username": username, "password": password},
            timeout=20,
        )
        payload = self._decode(response)
        self.csrf = str(payload.get("csrf_token") or "")
        self.cookie_header = extract_cookie_header(response)
        if not self.csrf:
            raise RunnerAPIError("Login response did not contain a CSRF token; sign in through the application and retry.")

    @staticmethod
    def _decode(response: requests.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise RunnerAPIError(f"Runner returned non-JSON HTTP {response.status_code}.") from exc
        if not response.ok:
            error = body.get("error") if isinstance(body, dict) else {}
            error = error if isinstance(error, dict) else {}
            message = error.get("message") or f"HTTP {response.status_code}"
            code = error.get("code")
            raise RunnerAPIError(f"{message}" + (f" [{code}]" if code else ""))
        if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            raise RunnerAPIError("Runner response did not contain the expected JSON data envelope.")
        return body["data"]

    def request(self, method: str, path: str, *, json_body: dict | None = None,
                params: dict | None = None, files: dict | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json", "Cookie": self.cookie_header}
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers["X-CSRF-Token"] = self.csrf
        if method.upper() == "POST":
            headers["Idempotency-Key"] = str(uuid.uuid4())
        response = self.session.request(
            method.upper(), urljoin(self.api_base, path.lstrip("/")),
            json=json_body, params=params, files=files, headers=headers, timeout=45,
        )
        return self._decode(response)

    def get_items(self, path: str, *, params: dict | None = None) -> list[dict[str, Any]]:
        data = self.request("GET", path, params=params)
        items = data.get("items", [])
        if not isinstance(items, list):
            raise RunnerAPIError(f"The {path} response did not contain an items array.")
        return items


def find_by(rows: list[dict[str, Any]], **fields: Any) -> dict[str, Any] | None:
    for row in rows:
        if all(row.get(key) == value for key, value in fields.items()):
            return row
    return None


def seed_workspace(client: RunnerClient) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    organizations = client.get_items("workspace/organizations")
    organization = find_by(organizations, slug="netregress-demo")
    if organization is None:
        organization = client.request("POST", "workspace/organizations", json_body={
            "slug": "netregress-demo", "name": "NetRegress Demo",
        })
        print(f"[CREATED] Organization: {organization.get('name')} ({organization.get('organization_id')})")
    else:
        print(f"[REUSED] Organization: {organization.get('name')} ({organization.get('organization_id')})")

    projects = client.get_items("workspace/projects", params={"organization_id": organization["organization_id"]})
    project = find_by(projects, slug="network-engineering-showcase")
    if project is None:
        project = client.request("POST", "workspace/projects", json_body={
            "organization_id": organization["organization_id"],
            "slug": "network-engineering-showcase",
            "name": "Network Engineering Showcase",
        })
        print(f"[CREATED] Project: {project.get('name')} ({project.get('project_id')})")
    else:
        print(f"[REUSED] Project: {project.get('name')} ({project.get('project_id')})")

    labs = client.get_items(f"workspace/projects/{project['project_id']}/labs")
    lab = find_by(labs, name="Topology Demo Lab")
    if lab is None:
        lab = client.request("POST", f"workspace/projects/{project['project_id']}/labs", json_body={
            "name": "Topology Demo Lab", "provider_id": "gns3",
        })
        print(f"[CREATED] Lab: {lab.get('name')} ({lab.get('lab_id')})")
    else:
        print(f"[REUSED] Lab: {lab.get('name')} ({lab.get('lab_id')})")
    print("[INFO] The Lab provider_id is metadata only; no controller is bound or contacted.")
    return organization, project, lab


def seed_configuration(client: RunnerClient, project: dict[str, Any], lab: dict[str, Any]) -> dict[str, Any]:
    project_id = project["project_id"]
    schemas = client.get_items("configuration/schemas", params={"project_id": project_id})
    schema_row = find_by(schemas, schema_id="demo.wifi-lab.v1", version=1)
    if schema_row is None:
        schema_row = client.request("POST", "configuration/schemas", json_body={
            "project_id": project_id,
            "schema_id": "demo.wifi-lab.v1",
            "name": "Demo Wi-Fi Lab Settings",
            "version": 1,
            "definition": SCHEMA,
        })
        print(f"[CREATED] Configuration schema: {schema_row.get('schema_id')} v{schema_row.get('version')}")
    else:
        print(f"[REUSED] Configuration schema: {schema_row.get('schema_id')} v{schema_row.get('version')}")

    profiles = client.get_items("configuration/profiles", params={"project_id": project_id})
    profile = find_by(profiles, name="Demo Wi-Fi Lab Defaults", scope_type="LAB", scope_id=lab["lab_id"])
    if profile is None:
        profile = client.request("POST", "configuration/profiles", json_body={
            "project_id": project_id,
            "name": "Demo Wi-Fi Lab Defaults",
            "description": "Non-secret sample settings for exercising Configuration Profiles and the resolver.",
            "scope_type": "LAB",
            "scope_id": lab["lab_id"],
            "schema_record_id": schema_row["schema_record_id"],
        })
        print(f"[CREATED] Configuration profile: {profile.get('name')} ({profile.get('profile_id')})")
    else:
        print(f"[REUSED] Configuration profile: {profile.get('name')} ({profile.get('profile_id')})")

    revisions = client.get_items(f"configuration/profiles/{profile['profile_id']}/revisions")
    revision = next((row for row in revisions if row.get("values") == VALUES), None)
    if revision is None:
        revision = client.request("POST", f"configuration/profiles/{profile['profile_id']}/revisions", json_body={
            "values": VALUES,
            "provenance": {"source": "netregress-demo-showcase", "purpose": "non-secret UI demonstration"},
        })
        print(f"[CREATED] Configuration revision r{revision.get('revision_number')} ({revision.get('revision_id')})")
    else:
        print(f"[REUSED] Configuration revision r{revision.get('revision_number')} ({revision.get('revision_id')})")

    if revision.get("status") != "PUBLISHED":
        revision = client.request("POST", f"configuration/profiles/{profile['profile_id']}/publish", json_body={
            "revision_id": revision["revision_id"],
        })
        print(f"[PUBLISHED] Configuration revision ({revision.get('revision_id')})")

    assignments = client.get_items("configuration/assignments", params={"project_id": project_id})
    assignment = find_by(assignments, profile_id=profile["profile_id"], revision_id=revision["revision_id"],
                         target_type="LAB", target_id=lab["lab_id"])
    if assignment is None:
        assignment = client.request("POST", f"configuration/profiles/{profile['profile_id']}/apply", json_body={
            "revision_id": revision["revision_id"],
            "target_type": "LAB",
            "target_id": lab["lab_id"],
        })
        print(f"[ASSIGNED] Revision assigned to demo Lab ({assignment.get('assignment_id')})")
    else:
        print(f"[REUSED] Existing Lab configuration assignment ({assignment.get('assignment_id')})")
    return profile


def import_topologies(client: RunnerClient, project: dict[str, Any], lab: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = client.get_items("topologies", params={"project_id": project["project_id"]})
    imported = []
    for name, relative_path, media_type in TOPOLOGIES:
        existing = find_by(profiles, name=name)
        if existing is not None:
            imported.append(existing)
            print(f"[REUSED] Topology profile: {name} ({existing.get('profile_id')})")
            continue
        source_path = DEMO_ROOT / relative_path
        with source_path.open("rb") as stream:
            response = client.request("POST", "topologies/import/native", params=None, files={
                "project_id": (None, project["project_id"]),
                "name": (None, name),
                "scope_type": (None, "LAB"),
                "scope_id": (None, lab["lab_id"]),
                "file": (source_path.name, stream.read(), media_type),
            })
        profile = response.get("profile") if isinstance(response.get("profile"), dict) else response
        imported.append(profile)
        report = response.get("report", {})
        counts = report.get("counts", {}) if isinstance(report, dict) else {}
        print(f"[IMPORTED] {name}: nodes={counts.get('nodes', 'reported on profile')}, links={counts.get('links', 'reported on profile')}")
    return imported


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed an illustrative NetRegress workspace using the authenticated local API.")
    parser.add_argument("--api-base", default="http://127.0.0.1:5050/api/v1", help="Loopback API base URL, including /api/v1")
    parser.add_argument("--username", help="Global Owner username; prompted when omitted")
    parser.add_argument("--skip-native-import", action="store_true", help="Create workspace/configuration only")
    args = parser.parse_args()

    username = args.username or input("NetRegress Global Owner username: ").strip()
    password = getpass.getpass("NetRegress Global Owner password (not saved): ")
    if not username or not password:
        print("Username and password are required.", file=sys.stderr)
        return 2

    try:
        client = RunnerClient(args.api_base, username, password)
        print("[PASS] Authenticated with the local NetRegress API.")
        organization, project, lab = seed_workspace(client)
        profile = seed_configuration(client, project, lab)
        topology_profiles = [] if args.skip_native_import else import_topologies(client, project, lab)
        print("\nDemo workspace ready:")
        print(json.dumps({
            "organization_id": organization.get("organization_id"),
            "project_id": project.get("project_id"),
            "lab_id": lab.get("lab_id"),
            "configuration_profile_id": profile.get("profile_id"),
            "topology_profiles": [item.get("profile_id") for item in topology_profiles],
        }, indent=2))
        print("\nNo provider controller, device, Run, telemetry, capture, deployment, or success evidence was fabricated.")
        return 0
    except (requests.RequestException, OSError, RunnerAPIError, KeyError) as exc:
        print(f"[FAILED] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())