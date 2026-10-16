# STEP graph editing and compaction

## Parse records and identities

STEP entities form a directed reference graph: an entity `#n` references other entity IDs. Respect quoted strings, doubled apostrophes, and references/semicolons inside strings. A regex that blindly splits every semicolon or remaps every `#123` can damage names. `step_graph.py` tokenizes references outside strings and checks duplicate IDs, missing references, and exact retained-record roundtrips. Its supported profile excludes STEP comments and multiple DATA sections.

Preserve entity identity where appearance or assembly records refer to an existing solid. Do not coalesce coincident topology merely because two vertices or faces have equal coordinates.

Part identity follows:

```text
SHAPE_DEFINITION_REPRESENTATION -> PRODUCT_DEFINITION_SHAPE
  -> PRODUCT_DEFINITION -> PRODUCT_DEFINITION_FORMATION -> PRODUCT
```

The representation side contains the actual manifold solid roots. `NEXT_ASSEMBLY_USAGE_OCCURRENCE` identifies a parent and child product definition. Inspect these links before selecting by name: Pulsonix-style exports may place a definition named `R_0603_10k_1%` beneath independent wrappers named `R1`, `R2`, etc. The same definition can have hundreds of uses.

## Remove R_* and CC_* components

Select whole product names with case-sensitive prefixes `R_` and `CC_`, or user-supplied replacements. Remove all matching definitions and their placements, not a substring inside arbitrary property text.

For the tested independent-wrapper layout:

1. Identify matching child definitions, their occurrences, and parent placement wrappers. Verify every child of a wrapper is selected before discarding the wrapper. If a real parent assembly contains retained children, stop this helper path and implement removal of the selected child relationships plus updates to the parent's representation item lists.
2. Exclude matching product/formation/context metadata, shape-definition roots, occurrence links, placement product-definition shapes, and context-dependent representation relationships from the semantic roots.
3. Keep the application protocol, retained shape-definition and context-dependent representation roots, and retained product categories. A mixed product category needs an explicit list edit; do not drop retained products.
4. Walk those roots to establish live geometry. Keep `STYLED_ITEM` records only when their target geometry is live. For `OVER_RIDING_STYLED_ITEM`, distinguish the target geometry from the base style reference.
5. Filter the item lists in geometric presentation representations to live styles. Preserve retained style chains and contexts. Old styles must not pull deleted geometry back into the reachable graph.
6. Walk the final semantic and appearance roots and remove every unreachable record. Check that every unselected occurrence remains and no removed product is revived through metadata.

Do not generalize the helper's root allowlist to unknown STEP schemas without inspection. Materials, PMI, layers, or additional application metadata can require extra semantic roots. A parser success alone does not justify dropping unfamiliar records. Use `--inspect-schema` and follow [the schema-extension procedure](schema-extension.md) for classification, adapter criteria and regression evidence. The implemented void-solid extension recognizes both `MANIFOLD_SOLID_BREP` and its `BREP_WITH_VOIDS` subtype as direct solid roots; their inner shells and extrusion surfaces are preserved through the dependency graph.

## Replace solids and remove the old geometry

For each edited part, map only its changed original and donor manifold solid roots (including solids with voids) with explicit CAD evidence. Allocate fresh IDs for the donor's dependent geometry, remap its references, and replace those original solid-root definitions. Untouched bodies, including pins, retain their native records and styles. For the guarded native cylindrical-hole recovery, edit only the proven shell/face boundary lists as described in [the geometry method](geometry.md#native-recovery-for-isolated-cylindrical-cavities).

**This intermediate patch is not the deliverable.** It still contains old shells, faces, edges, curves, and points that were used by the replaced roots. Prune from active geometry and appearance roots before publishing. Merely appending replacement records makes the file larger even when the visible part is simpler.

When adapting a narrow patch, another safe strategy is to calculate the old roots' dependency closure, protect nodes still referenced by retained records, and discard only the unneeded remainder. Account for obsolete appearance records as well; stale styles can keep dead geometry reachable. The bundled pipeline performs the complete supported-profile root traversal after transplantation.

## Acceptance and publication

Verify the exact written candidate:

- Every reference resolves; every retained geometry/placement record remains identical except explicitly replaced solid roots.
- Selected products/occurrences are absent; retained definitions and instance counts match the expected inventory.
- Reimported shapes are valid, with expected solid and face counts, volumes, bounds, and protected holes.
- The earlier cleanup operations remain in effect when applying another stage.
- The file is no larger than the input. Report actual bytes as well as model simplification; file size alone is not proof of geometric correctness.

Do not wave through a changed untouched component by loosening a volume tolerance. First check numerical integration at a tighter tolerance and compare actual geometry. If a full export changes unrelated geometry, preserve the source records and transplant only the intended edited definitions.

Write privately, validate, recheck the source hash, verify a backup for in-place replacement, then publish atomically. Do not confuse CAD-kernel roundtrip validation with a readback by a downstream application.

## Validated carrier example, 2026-10-15

The original `at_carrier.stp` was 42,575,390 bytes. The board had 1,305 circular holes below 0.8 mm: 1,277 at 0.254 mm, 17 at 0.2 mm, nine at 0.762 mm, and two at 0.7 mm. The board went from 1,612 to 307 faces, preserving 301 holes at or above the threshold. Small blind holes in three retained part definitions brought the assembly total to 1,320 filled hole instances.

An intermediate transplanted file grew to 45,160,346 bytes because obsolete geometry remained. Removing 71,733 obsolete records reduced it to 42,062,603 bytes. A full CAD-writer export was rejected because an untouched connector's volume changed by about 0.429 mm3 even with tighter integration.

Removing 370 `R_*` and 282 `CC_*` instances across 83 definitions discarded a further 97,123 records. This intermediate result was 37,219,607 bytes with 61 retained part definitions, 177 placed instances, and 1,209 solids. The mandatory final [deduplication stage](deduplication.md) then reduced it to 31,113,710 bytes through native instancing. These numbers describe that case, not acceptance constants for other files. The reusable helper must derive its own expected counts.
