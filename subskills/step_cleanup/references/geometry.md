# Hole recognition and removal

## Establish geometric intent

Use the CAD kernel to interpret STEP solids, not numeric text substitution on circle radii. Source STEP coordinates and the CAD reader must use the same units before transplanting replacement geometry. The bundled helper deliberately requires millimetre contexts.

Inventory the complete assembly, but edit each unique retained part definition once. Repeated instances inherit the change. Count both definitions and placed occurrences in the report.

A small cylindrical face is not necessarily a hole. PCB exports contain many lead bends, connector recesses, pin surfaces, and fillets at these radii. For each analytic cylinder:

1. Calculate diameter as twice its radius.
2. Evaluate a point and the **actual oriented outward face normal** on the cylinder; project the point onto the cylinder axis to obtain its radial vector. An inward normal/radial dot product identifies an internal wall. `TopAbs_REVERSED` alone is insufficient: an indirect cylinder frame can reverse that interpretation.
3. Group coaxial walls by radius and axis line, treating reversed axis directions as equivalent. At an overlapping axial section, require a complete circumference. A bore may use two semicylindrical faces. Disconnected axial segments and rounded slot ends do not establish a complete bore by adding every face angle indiscriminately.
4. Compare against the user threshold with only a numerical precision allowance. The tested allowance is 1e-7 mm, not a machining clearance. Keep the threshold hole itself.

The helper recognizes analytic cylindrical holes and flat blind-bore floors. Threads, conical-only holes, non-circular passages, and mesh-derived approximations need separate evidence and an adapted operation. Do not interpret an empty analytic recognizer as proof that a faceted mesh has no holes.

## Fast path for a flat board

For a board with a proven constant-thickness rectangular extrusion, reuse its top face's outer wire and all retained inner wires. Omit only complete circular inner wires whose diameters meet the selection, then extrude through the original thickness. This avoids defeaturing thousands of vias individually.

The helper checks one solid, six planar faces, otherwise only cylindrical faces, a horizontal top, vertical bore axes, and through-wall spans equal to the board thickness. It refuses non-circular inner wires in this fast path. Do not rebuild a stepped, chamfered, slotted, or counterbored board as a plain plate without additional proof.

Verify the omitted wire count equals the selected bore count. Expected added volume for through holes is:

```text
sum(pi * (diameter / 2)^2 * thickness)
```

Check the reconstructed volume against that value, unchanged outer bounds, unchanged solid count, and every protected bore's diameter, axis line, and depth. Canonicalize axis signs and axial coordinates before comparing features.

## General retained-part path

For a supported non-plate part, use `BRepAlgoAPI_Defeaturing` on the exact selected wall faces. Include a flat blind-hole floor only when its boundary edges are all shared with selected walls and its area fits the bore cap. This prevents deletion of an adjacent external plane or an unrelated package detail. Reject invalid results or missed holes instead of silently accepting a partial operation.

Require:

- Valid solids with the original solid count and outer bounds.
- No remaining selected complete bores.
- Unchanged protected bore keys.
- No original material removed by hole filling: `original.cut(edited).Volume()` is negligible.
- Added material consistent with the actual cavity, using the exact cylinder formula for a simple through board.

## Export without changing unrelated components

Export each edited part to a private donor STEP. Import it to establish the actual donor solid geometry, then map its solid roots to the source part using verified per-solid bounds. Reject duplicate/ambiguous bounds instead of assuming the exporter preserves solid order; a body and its pins can have different colors.

The helper uses `StepToTopoDS_Builder` if the reader has not recorded a direct `ShapeResult` for a manifold solid. STEP file entity IDs and reader entity ranks are not interchangeable; resolve the ID through the reader model.

Transplant only those verified solid definitions and the geometry they reference. Keep retained components' original geometry, labels, placements, and style records. Prune obsolete definitions afterwards using the linked STEP graph method. A full writer export is diagnostic until its effects on unrelated geometry are proven acceptable.

The helper preserves appearance references whose target source entities remain live. It removes styles aimed at obsolete faces as part of compaction; it does not automatically map individual old-face colors onto a newly exported face. When edited packages have important face-level appearance, supply and verify that correspondence as an additional step. Unedited parts keep their original geometry and style targets.
