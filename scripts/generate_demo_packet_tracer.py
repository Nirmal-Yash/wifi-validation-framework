#!/usr/bin/env python3
"""Generate and codec-validate a small Packet Tracer .pkt demonstration fixture.

This is a local fixture generator only. It does not launch Packet Tracer,
emulate a network, contact devices, or certify desktop-application reopening.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
# Running python scripts/generate_demo_packet_tracer.py puts scripts/ at
# sys.path[0]. Add the checkout root so the local lib package resolves even
# when the caller's working directory is different.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "examples" / "demo-showcase" / "native-projects" / "NetRegress-Packet-Tracer-Branch.pkt"


def create_packet() -> bytes:
    try:
        import pktlib
    except ImportError as exc:
        raise RuntimeError(
            "pktlib is not installed in this Python environment. Activate wifi-venv "
            "and install the repository's hash-locked requirements before generating the sample."
        ) from exc

    network = pktlib.new(seed=7)
    router = network.router("R1", "2911", at=(120, 180))
    pc = network.pc(
        "PC1",
        at=(420, 180),
        ip="192.0.2.2/24",
        gateway="192.0.2.1",
    )
    router["g0/0"].address = "192.0.2.1/24"
    pc["fa0"].connect(router["g0/0"])
    return network.to_bytes()


def validate_packet(content: bytes) -> tuple[int, int]:
    from lib.services.packet_tracer_interop import PacketTracerInteropService

    network = PacketTracerInteropService._load(content)
    definition, _mapping, report = PacketTracerInteropService._convert_network(network)
    node_count = len(definition.get("nodes", []))
    link_count = len(definition.get("links", []))
    if node_count < 2 or link_count < 1:
        raise RuntimeError("Generated Packet Tracer fixture did not contain the expected router/PC link.")
    reported = report.get("counts", {})
    if reported and (
        int(reported.get("nodes", node_count)) != node_count
        or int(reported.get("links", link_count)) != link_count
    ):
        raise RuntimeError("Packet Tracer codec report disagrees with the decoded topology.")
    return node_count, link_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a small, codec-readable Packet Tracer sample for manual Topology Studio import."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output .pkt path")
    parser.add_argument("--force", action="store_true", help="Explicitly replace an existing output file")
    args = parser.parse_args(argv)

    output = args.output.expanduser()
    if output.suffix.lower() != ".pkt":
        print("[FAIL] Output filename must end in .pkt.", file=sys.stderr)
        return 2
    if output.exists() and not args.force:
        print(f"[FAIL] Refusing to overwrite existing file: {output} (pass --force to replace it).", file=sys.stderr)
        return 2

    try:
        content = create_packet()
        nodes, links = validate_packet(content)
        output.parent.mkdir(parents=True, exist_ok=True)
        if args.force:
            output.write_bytes(content)
        else:
            with output.open("xb") as handle:
                handle.write(content)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    print("[PASS] Generated and codec-validated Packet Tracer fixture.")
    print(f"File: {output}")
    print(f"Bytes: {len(content)}")
    print(f"Nodes: {nodes}")
    print(f"Links: {links}")
    print(f"SHA-256: {hashlib.sha256(content).hexdigest()}")
    print("Desktop reopen in licensed Cisco Packet Tracer is NOT VERIFIED by this helper.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
