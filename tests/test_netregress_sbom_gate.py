from __future__ import annotations

import pytest

from scripts.netregress_sbom_gate import enforce, validate_sbom


def _sbom():
    return {
        "packages": [
            {"name": "requests", "versionInfo": "2.33.0", "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": "pkg:pypi/requests@2.33.0"}]},
            {"name": "react", "versionInfo": "19.1.0", "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": "pkg:npm/react@19.1.0"}]},
            {"name": "tauri", "versionInfo": "2.0.0", "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": "pkg:cargo/tauri@2.0.0"}]},
        ]
    }


def _match(name, version, purl, severity="High"):
    return {
        "artifact": {"name": name, "version": version, "purl": purl},
        "vulnerability": {"id": "CVE-2026-12345", "severity": severity},
    }


def test_app_sbom_requires_python_npm_and_cargo_ecosystems():
    result = validate_sbom(_sbom())
    assert result["status"] == "PASS"
    assert result["package_count"] == 3


def test_os_package_is_not_accepted_as_application_dependency():
    sbom = {
        "packages": [
            {"name": "libc6", "versionInfo": "2.39", "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": "pkg:deb/ubuntu/libc6@2.39"}]}
        ]
    }
    with pytest.raises(ValueError, match="non-application package ecosystems"):
        validate_sbom(sbom)


def test_high_or_critical_application_finding_blocks():
    result = enforce(
        _sbom(),
        {"descriptor": {"version": "0.110.0"}, "matches": [_match("requests", "2.33.0", "pkg:pypi/requests@2.33.0")]},
    )
    assert result["status"] == "FAIL"
    assert result["high_or_critical_application_findings"]


def test_unmapped_high_or_critical_finding_fails_closed():
    result = enforce(
        _sbom(),
        {"matches": [_match("openssl", "3.0.0", "pkg:generic/openssl@3.0.0")]},
    )
    assert result["status"] == "FAIL"
    assert result["unmapped_high_or_critical_findings"]


def test_medium_finding_does_not_block():
    result = enforce(
        _sbom(),
        {"matches": [_match("requests", "2.33.0", "pkg:pypi/requests@2.33.0", "Medium")]},
    )
    assert result["status"] == "PASS"


def test_non_purl_external_reference_is_not_treated_as_package_url():
    sbom = {
        "packages": [
            {
                "name": "requests",
                "versionInfo": "2.33.0",
                "externalRefs": [
                    {
                        "referenceType": "PACKAGE-MANAGER",
                        "referenceLocator": "pkg:pypi/requests@2.33.0",
                    }
                ],
            }
        ]
    }
    with pytest.raises(ValueError, match="no supported Python, npm or Cargo package PURLs"):
        validate_sbom(sbom)
