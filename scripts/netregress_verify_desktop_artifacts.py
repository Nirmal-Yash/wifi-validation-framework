#!/usr/bin/env python3
"""Verify exact-commit Linux desktop artifacts as an independent consumer."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
UBUNTU_BUILDS = ("ubuntu-22.04", "ubuntu-24.04")
SPDX_SBOM_PREDICATE = "https://spdx.dev/Document/v2.3"
DESKTOP_WORKFLOW = ".github/workflows/desktop-linux.yml"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_checked(command: Sequence[str]) -> None:
    result = subprocess.run(list(command), capture_output=True, text=True, check=False, timeout=180)
    if result.returncode:
        raise RuntimeError(f"consumer verification failed ({result.returncode}): {(result.stderr or result.stdout)[-2000:]}")


def _verify_checksum(package: Path, build_root: Path) -> str:
    if package.is_symlink() or not package.is_file():
        raise RuntimeError(f"package is missing or is a symlink: {package.name}")
    checksum_file = None
    for parent in (package.parent, *package.parents):
        if not parent.resolve().is_relative_to(build_root.resolve()):
            break
        candidate = parent / "SHA256SUMS"
        if candidate.is_file() and not candidate.is_symlink():
            checksum_file = candidate
            break
    if checksum_file is None:
        raise RuntimeError(f"SHA256SUMS is missing for {package.name}")
    expected = None
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        if len(line) >= 67 and line[64:66] in {"  ", " *"} and Path(line[66:].lstrip("*").strip()).name == package.name:
            expected = line[:64].lower()
            break
    if expected is None or len(expected) != 64:
        raise RuntimeError(f"SHA256SUMS has no valid entry for {package.name}")
    observed = _sha256(package)
    if observed != expected:
        raise RuntimeError(f"SHA-256 mismatch for {package.name}")
    return observed


def _license_inventory(sbom_path: Path) -> dict[str, object]:
    document = json.loads(sbom_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("spdxVersion") not in {"SPDX-2.2", "SPDX-2.3"}:
        raise RuntimeError("source SBOM is not a supported SPDX JSON document")
    packages = document.get("packages")
    if not isinstance(packages, list) or not packages:
        raise RuntimeError("source SBOM has no package inventory")
    declared, concluded, review = set(), set(), []
    for package in packages:
        if not isinstance(package, dict):
            review.append({"name": "UNKNOWN", "reason": "malformed SPDX package"})
            continue
        name = str(package.get("name") or "UNKNOWN")
        declared_license = str(package.get("licenseDeclared") or "NOASSERTION")
        concluded_license = str(package.get("licenseConcluded") or "NOASSERTION")
        declared.add(declared_license)
        concluded.add(concluded_license)
        if declared_license.upper() in {"", "NOASSERTION", "NONE"} or concluded_license.upper() in {"", "NOASSERTION", "NONE"}:
            review.append({
                "name": name, "version": str(package.get("versionInfo") or ""),
                "license_declared": declared_license, "license_concluded": concluded_license,
                "reason": "license declaration or conclusion requires human review",
            })
    return {
        "spdx_version": document["spdxVersion"], "package_count": len(packages),
        "declared_license_expressions": sorted(declared), "concluded_license_expressions": sorted(concluded),
        "review_required": review, "review_required_count": len(review),
        "approval_status": "REVIEW_REQUIRED" if review else "READY_FOR_APPROVAL",
    }


def verify_desktop_artifacts(artifact_root: str | Path, *, repository: str, source_commit: str,
                             run_command: Callable[[Sequence[str]], None] = _run_checked):
    root = Path(artifact_root).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"downloaded artifact root is unavailable: {root}")
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit.lower()):
        raise ValueError("source commit must be a full 40-character Git SHA")
    if not repository or "/" not in repository:
        raise ValueError("repository must use owner/name form")
    # Phase one is strictly local: validate the complete artifact set before
    # making any network/API attestation calls. A bad package must prevent
    # partial verification of a mixed good/bad release packet.
    pending = []
    licenses = {}
    signer_workflow = f"{repository}/{DESKTOP_WORKFLOW}"
    for os_version in UBUNTU_BUILDS:
        build_root = root / f"netregress-linux-desktop-{os_version}-{source_commit}"
        if not build_root.is_dir():
            raise RuntimeError(f"expected desktop build artifact is missing: {build_root.name}")
        packages = sorted(p for p in build_root.rglob("*") if p.is_file() and p.suffix.lower() in {".deb", ".appimage"})
        debs = [p for p in packages if p.suffix.lower() == ".deb"]
        appimages = [p for p in packages if p.suffix.lower() == ".appimage"]
        if len(debs) != 1 or len(appimages) != 1 or len(packages) != 2:
            raise RuntimeError(f"{os_version} must contain exactly one Debian package and one AppImage")
        sboms = list(build_root.rglob("netregress-source.spdx.json"))
        if len(sboms) != 1 or sboms[0].is_symlink():
            raise RuntimeError(f"{os_version} must contain exactly one source SPDX SBOM")
        licenses[os_version] = _license_inventory(sboms[0])
        for package in packages:
            if package.is_symlink() or not package.resolve().is_relative_to(build_root):
                raise RuntimeError(f"package path escapes its build artifact: {package.name}")
            digest = _verify_checksum(package, build_root)
            pending.append((os_version, package, digest))

    # Phase two only runs after every package in both Ubuntu builds passes the
    # local integrity checks above.
    verified = []
    for os_version, package, digest in pending:
        common = ["gh", "attestation", "verify", str(package), "--repo", repository,
                  "--signer-workflow", signer_workflow, "--source-digest", source_commit]
        run_command(common)
        run_command([*common, "--predicate-type", SPDX_SBOM_PREDICATE])
        verified.append({
            "os": os_version, "name": package.name, "sha256": digest,
            "provenance_attestation": "VERIFIED", "spdx_sbom_attestation": "VERIFIED",
        })
    return {
        "schema_version": "netregress-desktop-artifact-verification.v1",
        "source_commit": source_commit, "repository": repository,
        "package_count": len(verified), "packages": verified,
        "license_review": licenses, "license_approval": "REQUIRED",
        "status": "VERIFIED_WITH_LICENSE_REVIEW_REQUIRED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "desktop-artifact-verification.json")
    args = parser.parse_args(argv)
    output = args.output.expanduser()
    if not output.is_absolute():
        output = ROOT / output
    try:
        report = verify_desktop_artifacts(args.artifact_root, repository=args.repository, source_commit=args.commit)
    except Exception as exc:
        report = {"schema_version": "netregress-desktop-artifact-verification.v1",
                  "status": "FAIL", "error": f"{type(exc).__name__}: {exc}", "source_commit": args.commit}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
