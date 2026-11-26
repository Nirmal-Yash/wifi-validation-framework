# Stage G G08 — Vendor-Aware Native Topology Rendering

**Date:** 2026-11-26  
**Requirement:** RQ-061  
**Phase state:** Implemented pending exact-head quality workflow.

## Implemented behavior

- Topology Studio selects the most recent immutable presentation revision pinned to the active topology revision and renders it with the canonical topology as the semantic identity source.
- Native coordinates are rendered using the presentation's origin and axis directions, including negative positions and centered/bottom-left coordinate systems. Canvas fitting and zoom are independent of the older positive-only canonical viewport bounds.
- Native node dimensions, rotation, labels, native identifiers and interface port anchors are rendered when supplied.
- Link routes support straight, orthogonal, curved and explicit point sequences. Link labels and native port labels remain associated with canonical link endpoints.
- Rectangle, ellipse, line/freehand, text and image-reference drawings are rendered. Layer visibility and layer lock state are respected.
- Grid visibility and grid spacing follow the persisted presentation model; automatic layout remains an explicit user command.
- Native node dragging and coordinate inspector changes update presentation drafts only. They do not change canonical node coordinates, interface assignments, topology hashes or provider state.
- Snapshot capture retains the existing format/version/source artifact association and existing presentation extensions, drawings, layers, route points and port anchors. It also saves viewport state.
- Packet Tracer presentation coordinates now retain the original native device positions while the normalization transform is recorded separately; this avoids applying the canonical coordinate offset twice during display/export.

## Explicit limitations

Some codecs preserve drawing objects and icon references only in their immutable source bytes rather than projecting all of them into the G02 schema. External image assets are not fetched from emulator/controller filesystems. Where no image bytes are part of the source artifact, the canvas shows an asset-reference placeholder. Native desktop reopening remains an external acceptance step and is not inferred from an SVG render or codec self-read-back.

## Verification

New frontend unit tests cover native coordinate transforms, negative coordinates, presentation-only movement, geometry, path routing and layer visibility. Packet Tracer codec tests cover its raw native coordinate map. Existing topology editing, viewport, frontend build and full backend correctness gates remain required.
