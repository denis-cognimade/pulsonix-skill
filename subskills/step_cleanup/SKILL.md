---
name: step_cleanup
description: Simplify PCB STEP exports by filling small holes, removing R_* and CC_* components, pruning unused records, and deduplicating repeated solids into shared geometry. Use for Pulsonix PCB STEP cleanup and geometry instancing while preserving retained components.
---

# PCB STEP cleanup

Clean the actual STEP data, not just its visible model. Fill selected holes, remove selected components, eliminate obsolete records, and deduplicate repeated solids into shared geometry. Preserve the geometry, placements, and appearance of retained parts. **Deduplication is a mandatory final cleanup stage**, implemented by the default command; do not stop after hole/component removal or present instancing as an optional enhancement. A scan finding no compatible duplicates is a valid completed stage.

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

The library helpers are reusable independently:

- [cad_geometry.py](scripts/modules/cad_geometry.py): CAD inventory, inward-cylinder recognition, complete-bore grouping, fast flat-board reconstruction, guarded blind-hole defeaturing, and instance counting.
- [step_graph.py](scripts/modules/step_graph.py): STEP entity/reference graph, native record preservation, solid transplantation, component/placement pruning, style filtering, and unused-record removal.
- [step_instancing.py](scripts/modules/step_instancing.py): mandatory final stage, using [instancing_plan.py](scripts/modules/instancing_plan.py), [instancing_graph.py](scripts/modules/instancing_graph.py), and [instancing_audit.py](scripts/modules/instancing_audit.py) for matching, native representation maps, and validation.

For an export already cleaned by the earlier method, run just the final stage:

```powershell
python "<skill>/scripts/step_deduplicate.py" board_cleaned.stp --output board_instanced.stp
```

This preserves the source and writes an adjacent `.instancing.json` report. The full cleanup command already runs this stage and includes its results in `.cleanup.json`; a second command is unnecessary.

## Scope and workflow

The helpers accept millimetre Open CASCADE/Pulsonix-style AP214 exports with direct manifold solid definitions and independent component-placement wrappers. The final stage produces mapped geometry. Inputs already containing `MAPPED_ITEM` require a separate adapter; these commands reject them explicitly, so start a new cleanup from the original direct-BRep export. They also reject mixed parent assemblies during named-component removal, ambiguous product/solid correspondence, non-millimetre contexts, STEP comments/multiple DATA sections, and unsupported simple record families. Inspect the actual schema before adapting these cases. Styles on retained source entities are preserved; face-specific styles on reconstructed solids need explicit face correspondence if that appearance must also survive. Do not claim visual application validation from the kernel checks alone.

1. Record the source hash and size. Inventory part names, definitions versus placed instances, bores, volumes, bounds, and solid validity. Count shared definitions separately from their uses.
2. Read [the geometry method](references/geometry.md) before changing the hole logic. Use a complete bore circumference and actual face normals to distinguish holes from lead bends, small pins, and concave fillets.
3. Read [the STEP graph method](references/step-graph.md) before adapting removal, transplantation, or compaction. Preserve untouched records; do not deliver a full re-export that changes unrelated geometry or an appended patch that leaves obsolete data behind.
4. Reopen the defeatured candidate. Confirm selected items are absent, retained part names/counts and solid validity match, protected holes and outer bounds are unchanged, and there are no dangling references. The helper also compares volumes and face inventories against the intended result.
5. Read [deduplication](references/deduplication.md) and run the mandatory instancing stage. Match geometry and appearance, prove rigid equivalence, replace duplicate solids with native `MAPPED_ITEM` references, and prune obsolete topology/styles again. Reopen and verify every named assembly root, resolved appearance, physical solid count, and actual shared kernel geometry. Product definitions and placements remain separate even when their solids share a prototype.
6. Publish only after those checks and a fresh source-hash check. Report holes per definition and per instance, removed component counts, discarded records, stored geometry before/after, mapped instances, byte sizes, and output/backup paths. A cleanup should not make the STEP larger; the command refuses a larger candidate.

General defeaturing can be very slow on thousands of board vias. Use the verified constant-thickness extrusion path when applicable. Keep long CAD work observable through logging and progress updates; a tool timeout is not evidence of a failed or completed operation.

## Verification

Run the bundled behavioral tests after changing helpers:

```powershell
python "<skill>/tests/test_cleanup.py"
python "<skill>/tests/test_instancing.py"
```

They exercise STEP strings, CLI failures, selected component removal, the strict hole threshold, blind holes versus small external pins, mixed-parent refusal, backups, and mandatory instancing with rotation/translation, different colors, actual shared topology, unchanged metadata, and a successful no-match scan. Repeated cleanup is tested on direct-BRep results without mapped items. Preserve user files during skill tests. Report Open CASCADE roundtrip validation separately from loading the result in Pulsonix or SolidWorks. The carrier deduplication method was confirmed working by the user on 2026-10-15; see the reference for measured results.
