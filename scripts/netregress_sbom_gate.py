#!/usr/bin/env python3
"""Validate and enforce the NetRegress application dependency SBOM policy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

APP_PURL_PREFIXES = ("pkg:pypi/", "pkg:npm/", "pkg:cargo/")
REQUIRED_ECOSYSTEMS = ("pkg:pypi/", "pkg:npm/", "pkg:cargo/")
BLOCKING_SEVERITIES = {"high", "critical"}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read {path}: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _package_manager_purls(package: dict[str, Any]) -> list[str]:
    refs = package.get("externalRefs") or []
    values: list[str] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        # SPDX 2.3 represents a package URL using the PACKAGE-MANAGER
        # reference category and the "purl" reference type.
        if str(ref.get("referenceCategory") or "").upper() != "PACKAGE-MANAGER":
            continue
        if str(ref.get("referenceType") or "").lower() != "purl":
            continue
        locator = ref.get("referenceLocator")
        if isinstance(locator, str) and locator.startswith("pkg:"):
            values.append(locator.lower())
    return values


def _application_index(sbom: dict[str, Any]) -> dict[str, dict[str, str]]:
    packages = sbom.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("application SBOM is empty")

    index: dict[str, dict[str, str]] = {}
    unsupported: list[str] = []
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("SBOM contains malformed package entry")
        purls = _package_manager_purls(package)
        if not purls:
            # SPDX document/source packages may not have a package-manager PURL.
            # They are not vulnerability candidates; Grype matches that cannot
            # be tied to a validated app PURL still fail closed below.
            continue
        app_purls = [purl for purl in purls if purl.startswith(APP_PURL_PREFIXES)]
        unsupported_purls = [purl for purl in purls if not purl.startswith(APP_PURL_PREFIXES)]
        if unsupported_purls:
            unsupported.append(f"{package.get('name', 'UNKNOWN')}: {', '.join(unsupported_purls)}")
        for purl in app_purls:
            index[purl] = {
                "name": str(package.get("name") or "UNKNOWN"),
                "version": str(package.get("versionInfo") or "UNKNOWN"),
                "purl": purl,
            }
    if unsupported:
        raise ValueError("SBOM contains non-application package ecosystems: " + "; ".join(unsupported[:20]))
    if not index:
        raise ValueError("SBOM contains no supported Python, npm or Cargo package PURLs")

    missing = [prefix.rstrip("/") for prefix in REQUIRED_ECOSYSTEMS if not any(
        purl.startswith(prefix) for purl in index
    )]
    if missing:
        raise ValueError("SBOM is missing required application ecosystems: " + ", ".join(missing))
    return index


def validate_sbom(sbom: dict[str, Any]) -> dict[str, Any]:
    index = _application_index(sbom)
    return {
        "schema_version": "netregress-application-sbom.v1",
        "status": "PASS",
        "package_count": len(index),
        "ecosystems": sorted({purl.split("/", 1)[0] for purl in index}),
    }


def enforce(sbom: dict[str, Any], grype: dict[str, Any]) -> dict[str, Any]:
    validation = validate_sbom(sbom)
    index = _application_index(sbom)
    matches = grype.get("matches")
    if not isinstance(matches, list):
        raise ValueError("Grype report has no matches array")

    blocking: list[dict[str, str]] = []
    unmapped: list[dict[str, str]] = []
    for match in matches:
        if not isinstance(match, dict):
            raise ValueError("Grype report contains malformed match entry")
        vulnerability = match.get("vulnerability") or {}
        severity = str(vulnerability.get("severity") or "unknown").lower()
        if severity not in BLOCKING_SEVERITIES:
            continue
        artifact = match.get("artifact") or {}
        purl = str(artifact.get("purl") or "").lower()
        finding = {
            "id": str(vulnerability.get("id") or "UNKNOWN"),
            "package": str(artifact.get("name") or "UNKNOWN"),
            "version": str(artifact.get("version") or "UNKNOWN"),
            "severity": severity,
            "purl": purl or "MISSING",
        }
        if purl in index:
            blocking.append(finding)
        else:
            unmapped.append({
                **finding,
                "reason": "high/critical Grype match cannot be mapped to an approved application SBOM PURL",
            })

    return {
        "schema_version": "netregress-vulnerability-gate.v2",
        "status": "FAIL" if blocking or unmapped else "PASS",
        "sbom_validation": validation,
        "grype_version": (grype.get("descriptor") or {}).get("version"),
        "grype_match_count": len(matches),
        "high_or_critical_application_findings": blocking,
        "unmapped_high_or_critical_findings": unmapped,
        "policy": "High/critical findings in application dependencies block; unmapped high/critical findings also block.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--sbom", required=True, type=Path)
    scan = commands.add_parser("enforce")
    scan.add_argument("--sbom", required=True, type=Path)
    scan.add_argument("--grype-report", required=True, type=Path)
    scan.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        sbom = _load_json(args.sbom)
        result = validate_sbom(sbom) if args.command == "validate" else enforce(sbom, _load_json(args.grype_report))
    except Exception as exc:
        result = {
            "schema_version": "netregress-vulnerability-gate.v2",
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }

    if args.command == "validate":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
