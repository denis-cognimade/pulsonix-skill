# Geometry deduplication and native instancing

Run this mandatory final cleanup stage after hole filling, selected component removal, and pruning. It shares repeated solid geometry while preserving distinct products and placements. The default `step_cleanup.py` command runs it automatically; `step_deduplicate.py` applies this stage to an earlier cleaned export.

## Match and prove

`instancing_plan.py` recursively hashes solid dependency graphs independently of entity IDs. Normalize 3D points around a deterministic anchor and try all 24 proper axis rotations; rotate directions without translating them. Group by geometry **and appearance**, including styles attached to faces and inherited style chains. Mirroring and scaling are excluded. Coordinate rounding at 1e-8 mm only generates candidates, never establishes equality.

This is conservative matching of compatible STEP topology/parameterization under translation and these rotations. Independently reparameterized CAD exports and arbitrary rotations can remain unmatched. Do not describe the scan as a universal geometric equivalence solver. Do not combine same-shaped solids with different appearance merely to maximize reduction.

For each duplicate, derive the transform from prototype coordinates into duplicate coordinates. Use valid solids from the **full STEPCAF import** to check bounds, face counts, and two-way Boolean differences (missing and extra volume each at most 1e-6 mm3).

Important: `CadModel.entityShape()` can fall back to a low-level builder returning an unhealed, invalid pin. Use that result only to associate bounds with a unique, valid solid from the fully imported component. Boolean comparison against the raw fallback produced false mismatches in this case. Reject ambiguous correspondence.

## Write shared geometry

Keep the canonical `MANIFOLD_SOLID_BREP` and its native dependencies. Create a prototype `ADVANCED_BREP_SHAPE_REPRESENTATION` in the original unit context and a `REPRESENTATION_MAP` using an identity `AXIS2_PLACEMENT_3D`. Replace each duplicate solid **at its existing entity ID** with a `MAPPED_ITEM` referring to the map and its rigid target placement. The tested target is `AXIS2_PLACEMENT_3D`.

Change a containing `ADVANCED_BREP_SHAPE_REPRESENTATION` to generic `SHAPE_REPRESENTATION` when it now contains a mapped item. Preserve product names/definitions, occurrence records, and assembly transformations verbatim. This also shares repeated solids within a package, such as pins; merging only whole product definitions misses these savings.

Prune unreachable shells, faces, edges, curves, points, and obsolete appearance records after replacements. Appending maps while retaining the old topology defeats the cleanup. Keep styles on active mapped items/prototypes and let the appearance audit reject incompatible results. The graph helper recognizes the new mapping record families.

## Validate the written candidate

Reopen through STEPCAF. Internal prototypes can receive repeated generic names such as `SOLID`; `CadModel(..., internal_labels=True)` identifies these by unique label index. Keep default strict component-name handling elsewhere. Internal prototype labels are not product identities.

Compare named free assembly roots before/after: names, validity, physical solid/face counts, bounds rounded to 1e-5 mm, volume (1e-5 mm3), area (1e-4 mm2), and center of mass (1e-6 mm). Resolve inherited XCAF styles and compare per-face bounds/area, surface RGBA, curve RGB, and visibility. Check original `PRODUCT`, `PRODUCT_DEFINITION`, `NEXT_ASSEMBLY_USAGE_OCCURRENCE`, and `ITEM_DEFINED_TRANSFORMATION` records remain identical and every STEP reference resolves.

Count unique underlying solid geometries using `TopoDS_Shape.IsPartner`, ignoring their locations. When replacements exist this count must fall; fewer text records alone do not prove native instancing. Physical solids and retained component identities must remain unchanged. A scan with no compatible duplicates succeeds without modifying its input bytes.

Publish only the checked candidate, with a fresh source hash and no file-size increase. The standalone command writes a new file/report; the full command uses its existing backup/publication path. Neither command accepts an already mapped input: use the original direct-BRep export or implement and validate an adapter for that profile. Kernel checks do not establish compatibility with every downstream application.

## Confirmed carrier result, 2026-10-15

After hole removal, R_*/CC_* removal, and compaction, `at_carrier.stp` was 37,219,607 bytes. Deduplication produced `at_carrier_instanced.stp` at **31,113,710 bytes**, a further **16.41% reduction**. It created 260 mapped instances across 49 shared groups and reduced stored solid geometries from **485 to 225**, preserving **177 placed components and 1,209 physical solids**. Geometry, placements, metadata, and resolved appearances passed the checks above. The user then confirmed the result worked in their application. These are measured case results, not fixed acceptance counts for other boards.
