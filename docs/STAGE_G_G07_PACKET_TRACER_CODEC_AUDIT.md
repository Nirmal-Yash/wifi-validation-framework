# Stage G — G07 Cisco Packet Tracer Native Codec Integration

**Checkpoint:** 2026-11-26  
**Requirement:** RQ-060  
**Source status:** IMPLEMENTED_PENDING_CI on the G07 phase commit.  
**Scope:** join the existing Packet Tracer .pkt implementation to the generic G03 native-codec registry and G02 presentation/source-provenance lifecycle.

## Architecture

- PacketTracerTopologyCodec is registered as CISCO_PACKET_TRACER_PKT in default_registry().
- It reuses the existing PacketTracerInteropService pinned pktlib parser, bounded decompression preflight, DTD/entity rejection, canonical device/link projection and serializer. No parallel .pkt parser or database authority is introduced.
- The generic NativeTopologyInteropService creates the existing canonical topology profile/revision and G02 immutable source and presentation records. The source SHA-256 is pinned to the imported revision and presentation.
- The legacy /api/v1/topologies/import/packet-tracer, legacy native-source table, and matching export route remain intact for existing clients.
- Topology Studio's unified native import accepts .pkt through /api/v1/topologies/import/native; the unified source-artifact table includes Packet Tracer exports.

## Declared support boundary

| Operation | Support |
|---|---|
| Strict .pkt decode | Existing pinned pktlib implementation, with source/expanded XML bounds and DTD/entity rejection |
| Canonical projection | Supported device/interface/link subset from the existing Packet Tracer conversion service |
| Presentation projection | Node identity, label, normalized X/Y, interface-to-port identity and direct-link identity |
| Source preservation | Original .pkt bytes, SHA-256, codec/version and import metadata through G02 |
| Native export | Device name and X/Y placement only; existing device/link identities must remain unchanged |
| Read-back | pktlib reopen; device identity, name, coordinate and link endpoint checks |
| Not claimed | Desktop Packet Tracer reopening, lossless editing of all device models, modules, drawings, notes, interfaces, VLAN/IP/configuration or arbitrary links |

The codec uses the previously declared 3.5 MiB compressed-source and 24 MiB expanded XML limits from P07-B. It does not relax parser bounds or execute any contents of the uploaded project. The source release/version is recorded; the currently documented pktlib test baseline is Packet Tracer 8.2.0, and serializer output edition is reported rather than asserted to match the source version.

## Verification

Added registry, codec, unified import/export and provenance tests. Tests verify a byte-identical no-op export after pktlib read-back and ensure source/presentation revisions are associated. The generic serializer rejects unsupported semantic/topology changes. The legacy Packet Tracer API remains separately tested.

External acceptance still requires representative vendor-produced .pkt files from the specific release matrix and reopening exports in a licensed Packet Tracer desktop installation. No such live desktop test is claimed by source/CI verification.
