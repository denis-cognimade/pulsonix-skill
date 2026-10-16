---
name: step_cleanup
description: Simplify PCB STEP exports by filling small holes, removing R_* and CC_* components, pruning unused records, and deduplicating repeated solids into shared geometry. Use for Pulsonix PCB STEP cleanup and geometry instancing while preserving retained components.
---

# PCB STEP cleanup

Clean the actual STEP data, not just its visible model. Fill selected holes, remove selected components, eliminate obsolete records, and deduplicate repeated solids into shared geometry. Preserve the geometry, placements, and appearance of retained parts. **Deduplication is a mandatory final cleanup stage**, implemented by the default command; do not stop after hole/component removal or present instancing as an optional enhancement. A scan finding no compatible duplicates is a valid completed stage.

Identical components remain separate occurrences. Deduplication stores their geometry once in the same STEP file and references it from every use; it does not authorize deleting products or placements. Use ordinary assembly occurrences referencing shared internal BRep products. SolidWorks 2025 silently dropped repeated pins represented by `MAPPED_ITEM`, even though Open CASCADE counted them correctly; preserving the BRep subtype or changing the map target did not fix it. Removal applies only to the selected component prefixes.

The default preset is circular holes with diameter **strictly below 0.8 mm**, plus case-sensitive product-name prefixes **`R_` and `CC_`**. A hole exactly at the threshold remains. `R_*` means a STEP part name such as `R_0603_10k_1%`; it does not mean every instance designator beginning with `R`.

Use explicit user parameters instead of the defaults. A request for holes alone does not authorize removing components, and a request for named components alone does not authorize filling holes. These selections control defeaturing; the cleanup still finishes with pruning and deduplication unless the user explicitly limits it otherwise. Remove selected components first to avoid processing geometry that will be discarded.

## Helpers

[scripts/step_cleanup.py](scripts/step_cleanup.py) is a configurable command using the helpers in [scripts/modules](scripts/modules). It defaults to a new sibling output and writes an adjacent JSON report. It never publishes a candidate that fails its checks. Use installed Python with CadQuery/Open CASCADE; [requirements.txt](requirements.txt) records the tested CadQuery version. If dependencies are missing, install them in a suitable virtual environment rather than changing a global installation.

From the board file's directory, run:

```powershell
python "C:\Development\skills\pulsonix\subskills\step_cleanup\scripts\step_cleanup.py" board.stp
```

This produces `board_cleaned.stp` and `board_cleaned.stp.cleanup.json`. For other installations, resolve the helper path relative to this skill instead of assuming the example's absolute path.

```powershell
# Full preset, updating the requested file after validation and a verified backup.
python "<skill>/scripts/step_cleanup.py" board.stp --in-place

# Only holes; preserve components. Threshold is configurable, in millimetres.
python "<skill>/scripts/step_cleanup.py" board.stp --keep-components --hole-diameter 0.8

# Only matching components; preserve all holes.
python "<skill>/scripts/step_cleanup.py" board.stp --keep-holes --remove-prefix R_ --remove-prefix CC_

# Pruning and mandatory deduplication, preserving active geometry and components.
python "<skill>/scripts/step_cleanup.py" board.stp --keep-holes --keep-components --output board_compact.stp
```

`--remove-prefix` replaces the default prefix set and can be repeated. Existing output/report paths are not overwritten. Repeated in-place runs use a unique report name. `--in-place` backs up the current source with a unique `.bak` suffix and verifies its hash before replacement. Complete an already authorized in-place edit after validation; do not ask for another confirmation merely to publish it.

Inspect unfamiliar records before editing, without loading the CAD kernel:

```powershell
python "<skill>/scripts/step_cleanup.py" board.stp --inspect-schema > schema.json
```

The JSON lists family counts, up to three sample records per family, entity IDs, outgoing references and incoming referrers. Inspection accepts unfamiliar families; cleanup still refuses them. Follow [schema extension](references/schema-extension.md) for classification, implementation criteria, and required regression evidence. Do not merely add names to `KNOWN_TYPES` or bypass its rejection. The supported geometry includes `BREP_WITH_VOIDS`, `ORIENTED_CLOSED_SHELL`, and `SURFACE_OF_LINEAR_EXTRUSION`; void solids participate in transplantation and mandatory instancing as well as graph traversal.

The library helpers are reusable independently:

- [cad_geometry.py](scripts/modules/cad_geometry.py): CAD inventory, inward-cylinder recognition, complete-bore grouping, fast flat-board reconstruction, guarded blind-hole defeaturing, and instance counting.
- [step_graph.py](scripts/modules/step_graph.py): STEP entity/reference graph, native record preservation, solid transplantation, component/placement pruning, style filtering, and unused-record removal.
- [native_holes.py](scripts/modules/native_holes.py): guarded native boundary repair for isolated planar-ended cylinders missed by defeaturing, without re-exporting surrounding geometry.
- [step_instancing.py](scripts/modules/step_instancing.py): mandatory final stage, using [instancing_plan.py](scripts/modules/instancing_plan.py), [instancing_graph.py](scripts/modules/instancing_graph.py), and [instancing_audit.py](scripts/modules/instancing_audit.py) for matching, shared assembly products, and validation.
- [cleanup_diagnostics.py](scripts/modules/cleanup_diagnostics.py): automatic failure bundles, stage findings, rejected part and face exports, and optional independent bore trials.
- [verify_solidworks.py](scripts/verify_solidworks.py): optional application validation through an already running SolidWorks session, requiring `pywin32`. It imports an isolated copy, checks all body counts and shared occurrence transforms, saves a hash-bound report and restores the previous document. It does not save application documents or change import settings.

When SolidWorks compatibility is required, verify the candidate's actual bytes:

```powershell
python "<skill>/scripts/verify_solidworks.py" board_cleaned.stp --report board_cleaned.stp.solidworks.json
```

For an export already cleaned by the earlier method, run just the final stage:

```powershell
python "<skill>/scripts/step_deduplicate.py" board_cleaned.stp --output board_instanced.stp
```

This preserves the source and writes an adjacent `.instancing.json` report. The full cleanup command already runs this stage and includes its results in `.cleanup.json`; a second command is unnecessary.

## Scope and workflow

The helpers accept millimetre Open CASCADE/Pulsonix-style AP214 exports with direct manifold solid definitions (including solids with void shells) and independent component-placement wrappers. The final stage creates internal assembly products for affected packages and one occurrence for every solid use. Original component products and external placements remain intact. Inputs containing `MAPPED_ITEM` or the helper's `__STEP_SHARED_` products require a separate adapter and are rejected; start a new cleanup from the original direct-BRep export. They also reject mixed parent assemblies during named-component removal, ambiguous product/solid correspondence, non-millimetre contexts, STEP comments/multiple DATA sections, and unsupported simple record families. Follow the schema-extension procedure before adapting these cases. Untouched bodies retain native records. Face-specific styles on reconstructed bodies still need explicit correspondence; native boundary repair retains surviving face IDs and styles. Do not claim application validation from the kernel checks alone.

1. Record the source hash and size. Inventory part names, definitions versus placed instances, bores, volumes, bounds, and solid validity. Count shared definitions separately from their uses.
2. Read [the geometry method](references/geometry.md) before changing the hole logic. Use a complete bore circumference and actual face normals to distinguish holes from lead bends, small pins, and concave fillets.
3. Read [the STEP graph method](references/step-graph.md) before adapting removal, transplantation, or compaction. Preserve untouched records; do not deliver a full re-export that changes unrelated geometry or an appended patch that leaves obsolete data behind.
4. Reopen the defeatured candidate. Confirm selected items are absent, retained part names/counts and solid validity match, protected holes and outer bounds are unchanged, and there are no dangling references. The helper also compares volumes and face inventories against the intended result.
5. Read [deduplication](references/deduplication.md) and run the mandatory instancing stage. Match geometry and appearance, prove rigid equivalence, attach every solid use to its original product through ordinary assembly occurrences, and prune obsolete topology/styles again. Each duplicate points to one common prototype product definition and BRep. Reopen and verify every named assembly root, resolved appearance, physical solid count, and actual shared kernel geometry. Verify downstream body counts and pin positions in SolidWorks before claiming SolidWorks compatibility.
6. Publish only after those checks and a fresh source-hash check. Report holes per definition and per instance, removed component counts, discarded records, stored geometry before/after, shared instances, byte sizes, and output/backup paths. A cleanup should not make the STEP larger; the command refuses a larger candidate.

General defeaturing can be very slow on thousands of board vias. Use the verified constant-thickness extrusion path when applicable. Keep long CAD work observable through logging and progress updates; a tool timeout is not evidence of a failed or completed operation.

## Failure diagnosis and recovery

Every failure after work starts retains a unique sibling directory named `<output>.failed.<id>/` and logs its `failure.json` path. This also applies to `--in-place` failures before publication: the source stays unchanged and no cleanup success report is written. The report records source hashes before/after, the failing stage/product, completed stages, schema and baseline inventories, accepted earlier edits, and available artifact hashes. Unfinished stages are not marked as passed. A diagnostic export failure is reported separately and does not replace the original cleanup error. A hard process kill or machine failure cannot run this exception handler.

For a rejected hole operation, inspect `failed_part/bores.json`, `original_part.stp`, `rejected_part.stp` when the kernel returned a candidate, and `selected_faces.stp` when exportable. Bore records include diameter, canonical axis/depth key, wall face indices and parameter ranges; selected faces include blind floors, surface type, area and center. Checks record validity, solid count, bounds, remaining selected bores, protected bores and removed material. Face indices refer to the in-memory shape that was exported, are zero-based and are **not STEP entity IDs**; an importer may reorder faces. Locate them geometrically using the recorded measurements and the selected-face export.

The bundle also retains component-filtered and later assembly candidates that existed when the run failed. `partial_assembly.stp` contains previously accepted part edits, may still have obsolete records, and excludes the rejected edit. All bundle STEP files are diagnostic artifacts pending the complete pipeline checks. Do not rename a partial result into the requested output or call it a completed cleanup.

To isolate a stubborn bore, rerun from the unchanged source with a fresh output name and the same selection flags, adding:

```powershell
python "<skill>/scripts/step_cleanup.py" board.stp --output board_review.stp --diagnose-bores
```

On failure this additionally writes `failed_part/trials.json` and `bore_NNN_candidate.stp` for independent per-bore defeaturing trials. Each trial uses the same original part and selects only that bore's walls and proven floor. It records selected indices, kernel completion, target removal, remaining bores and geometry checks. These trials can be slow; progress is logged per bore. Follow [the recovery workflow](references/geometry.md#diagnose-a-partial-or-failed-operation) to compare failed and successful faces and implement a justified repair. `IsDone=True` alone does not establish removal. Keep the original selection and acceptance checks when retrying; never skip a failed product, raise the threshold, suppress the residual bore check, or publish a partial candidate to make a run pass.

## Verification

Run the bundled behavioral tests after changing helpers:

When fixing a reported board failure, also rerun the full requested preset from its unchanged original export. An instancing-only run with `--keep-holes --keep-components` does not validate hole removal or component filtering.

```powershell
python "<skill>/tests/test_cleanup.py"
python "<skill>/tests/test_instancing.py"
python "<skill>/tests/test_schema_and_diagnostics.py"
python "<skill>/tests/test_native_holes.py"
```

The suites exercise selection, hole thresholds, blind holes versus external pins, mixed-parent refusal, backups, diagnostics, native hole recovery, unchanged pin records, shared assembly references, transforms, colors, and a no-match scan. The failure-injection tests disable native recovery to verify an unrepaired partial result still fails. Repeated cleanup is tested on direct-BRep results without internal instancing. Preserve user files during tests. Report Open CASCADE validation separately from SolidWorks import checks. Earlier carrier success did not establish compatibility of mapped pins. The Envisense default-preset regression retained all 164 physical solids in 27 original components in SolidWorks 2025 SP3.0; all 54 internal shared occurrence transforms matched the STEP, with maximum translation error below 1e-10 mm. The user confirmed the final cleaned file worked on 2026-10-16; see [the confirmed result](references/deduplication.md#confirmed-envisense-result-2026-10-16) for the tested artifact and measurements.
