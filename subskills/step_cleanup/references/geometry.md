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

Process each solid of a multi-body package independently and keep untouched solids unchanged. Export/transplant only bodies that actually changed. Re-exporting all pins changes unrelated native topology and can lose face appearances.

Require:

- Valid solids with the original solid count and outer bounds.
- No remaining selected complete bores.
- Unchanged protected bore keys.
- No original material removed by hole filling: `original.cut(edited).Volume()` is negligible.
- Added material consistent with the actual cavity, using the exact cylinder formula for a simple through board.

## Native recovery for isolated cylindrical cavities

`native_holes.py` handles simple planar-ended bores when defeaturing fails. The original Envisense microphone's 0.15 mm bore remained after `IsDone=True`; exporting its surrounding body also changed its imported geometry, so a donor re-export was unsuitable.

The recovery matches native cylindrical surfaces to the recognized diameter, canonical axis line, axial endpoints and wall count. It proves a blind cylinder has one planar inner opening and one circular planar floor, or a through cylinder has two planar inner openings. Boundaries must use the selected circular rims; adjoining recesses and ambiguous coaxial surfaces are refused.

Edit only the owning `CLOSED_SHELL` face lists and the proven opening faces' inner boundary lists. Remove the selected walls and floors, retaining the surrounding surface, outer wires, other holes, entity IDs and styles. Reimport and require valid solids, unchanged counts/bounds/protected bores, exact expected face-count reduction, no selected bores and the analytic surface-area change. This native boundary proof establishes that only the chosen cavity is filled without a compound Boolean or geometry re-export. Keep it distinct from the general method's Boolean material check.

Report the analytic cavity volume and the kernel's measured volume delta separately: the original microphone gives unstable volume/Boolean results even though its native unchanged-face records and the surface-area proof agree. Do not loosen general volume tolerances to accommodate it. Retain the exact before/after native records in the report. If the native proof or reimport fails, restore the graph and preserve the original failure bundle.

## Diagnose a partial or failed operation

Treat kernel completion as an operation status, then run the geometric checks. Open CASCADE documents warning handling separately from `IsDone`; feature removal can return a shape that still needs inspection. See [the defeaturing API](https://occt3d.com/dev/doc/refman/html/class_b_rep_algo_a_p_i___defeaturing.html). The pinned OCP binding exposes `IsDone` but does not expose the C++ warning-report methods; the helper records unavailable warning status as `null`, never as proof that there were no warnings.

1. Open the automatically saved `<output>.failed.<id>/failure.json`. Verify the input options, source hash, failing product, stage and earlier completed stages. For `SPV61A0LR5H-1`, compare both selected diameters (0.25 and 0.15 mm) with the remaining-bore list. A 0.15 mm residual with unchanged validity, bounds and protected holes is still a failed cleanup.
2. Open `failed_part/bores.json`. Match original wall face indices to diameter, canonical axis line, axial range and angular spans. Compare the residual bore by its geometry key rather than its candidate face index: defeaturing can renumber faces. Inspect `original_part.stp`, `rejected_part.stp` and `selected_faces.stp` in a viewer. Use the recorded surface types, areas and centers to locate walls and floors after an import that changes face order. The face-only file is a diagnostic shell/compound, not a cleaned solid.
3. Rerun with `--diagnose-bores` and unchanged source/selection options. Each trial operates on one complete bore group from the original part, including only its proven planar floor. `trials.json` records target disappearance separately from other remaining selected holes; a successful one-bore probe need not remove the other selected bores. A probe passes diagnostically only if its target disappears and validity, solid count, bounds, protected-hole and material-preservation checks pass.
4. If the individual failed bore also fails, inspect its adjacency: split or trimmed cylindrical walls, floor ownership, shared edges, connected recesses and nonplanar caps. Confirm the inward-normal and complete-circumference classification first. Add any extra face only when geometry proves it belongs to the same selected cavity. Preserve pins, package recesses, external faces and protected holes. Save the proposed face set and candidate so the repair is reviewable.
5. If all individual probes succeed but the combined operation fails, test a sequential strategy in a separate diagnostic experiment. Recompute wall groups and face indices after each step; never reuse indices from the previous shape. Recheck against the original part after the complete sequence, including residual holes, protected bores, material preservation, bounds and validity. Prove order independence or document the justified ordering before making that strategy the default.
6. A local cavity-fill or reconstruction fallback needs its own regression fixture and geometric proof that only the selected cavity is filled. Do not plug a cylinder through a connected recess just because its nominal diameter matches. Keep alternative trials separate from the original rejected candidate. If the available evidence cannot establish a correct repair, retain the failure bundle and report the exact unresolved bore; do not claim completed cleanup.
7. After adapting the method, rerun the complete pipeline from the original source to a fresh output. Require the native STEP transplantation, pruning, geometry roundtrip, mandatory deduplication, size and fresh hash checks before publishing. Diagnostic STEP exports alone do not preserve the full assembly metadata/appearance contract.

The failure bundle preserves previously accepted edits in `partial_assembly.stp` when any existed, plus per-stage files. This allows review without replaying the whole board, but it is not a supported resume point: its obsolete records and unfinished stages still require validation. For reproducibility, return to the original source after the repair is implemented.

## Export without changing unrelated components

For the donor path, export only the changed solids of an edited part to a private STEP. Import it to establish the actual donor solid geometry, then map those roots to the source part using verified per-solid bounds. Leave untouched solid roots and their dependency/style records intact. Reject duplicate/ambiguous bounds instead of assuming the exporter preserves solid order; a body and its pins can have different colors. Native boundary recovery edits the source graph directly and does not use a donor re-export.

The helper uses `StepToTopoDS_Builder` if the reader has not recorded a direct `ShapeResult` for a manifold solid. STEP file entity IDs and reader entity ranks are not interchangeable; resolve the ID through the reader model.

Transplant only those verified solid definitions and the geometry they reference. Keep retained components' original geometry, labels, placements, and style records. Prune obsolete definitions afterwards using the linked STEP graph method. A full writer export is diagnostic until its effects on unrelated geometry are proven acceptable.

The helper preserves appearance references whose target source entities remain live. It removes styles aimed at obsolete faces as part of compaction; it does not automatically map individual old-face colors onto a newly exported face. When edited packages have important face-level appearance, supply and verify that correspondence as an additional step. Unedited parts keep their original geometry and style targets.
