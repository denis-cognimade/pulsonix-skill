# Geometry deduplication through shared assembly products

Run this mandatory final stage after hole filling, selected component removal, and pruning. It shares repeated BReps within one STEP file while retaining every physical use and the original component identities and placements.

## Match and prove

`instancing_plan.py` hashes geometry and appearance independently of entity IDs. It normalizes coordinates around an anchor and tries the 24 proper axis rotations. Coordinate rounding only generates candidates. Mirroring, scaling, arbitrary rotations and reparameterized equivalents are outside this conservative matcher.

For each candidate, use the valid solid from the full STEPCAF import to prove rigid equivalence with bounds, face counts and two-way Boolean differences. The low-level `CadModel.entityShape()` fallback is used only to associate bounds with a unique fully imported solid; it can return an unhealed shape unsuitable for Boolean comparisons.

## Write ordinary assembly occurrences

SolidWorks 2025 SP3.0 ignored repeated pins encoded as `MAPPED_ITEM` inside multi-body product representations. The Envisense mapped output contained 164 physical solids in Open CASCADE but imported only 135 in SolidWorks. A three-pin fixture imported one pin. Preserving advanced BRep representation types and using Cartesian map targets did not fix it. Do not restore that method based only on an Open CASCADE roundtrip or schema validity.

`AssemblyInstancing` uses the ordinary assembly structure emitted by CadQuery for repeated component occurrences:

1. Keep each canonical native solid and its dependencies. Create one internal product definition and `ADVANCED_BREP_SHAPE_REPRESENTATION` for it, named `__STEP_SHARED_<source-root>`.
2. Convert each affected original product's geometry representation to an assembly `SHAPE_REPRESENTATION` containing placements. Keep its original product definition, shape-definition link, name and external occurrences.
3. For **every** solid in that affected product, add a `NEXT_ASSEMBLY_USAGE_OCCURRENCE` under the original product definition. Include unique bodies as well as duplicate pins. Each occurrence references the appropriate internal prototype product; duplicates reference the same definition.
4. Connect the occurrence through its placement `PRODUCT_DEFINITION_SHAPE`, `CONTEXT_DEPENDENT_SHAPE_REPRESENTATION`, representation relationship and `ITEM_DEFINED_TRANSFORMATION`. Use identity origin and the proven rigid target placement.
5. Prune unused duplicate topology and styles. Retain styles on canonical solids and faces. The appearance audit checks resolved inherited styles in world coordinates.

The internal product hierarchy changes because pins become child occurrences. Original externally placed components remain intact. There are no external geometry files and no mapped items in the output.

## Validate

Audit each original solid use in every converted representation. It must have a child occurrence with the original parent definition, expected shared prototype and placement. All duplicates of a prototype use one product definition. Original product, product-definition, shape-definition, external occurrence and external transform records remain unchanged.

Reopen with STEPCAF and compare named free roots, validity, physical solid/face counts, bounds, volume, area, center of mass and resolved per-face appearance. Count underlying shared solid geometries using `TopoDS_Shape.IsPartner`. Shared definitions must decrease while physical uses remain unchanged.

Internal prototypes may have repeated or missing generic labels; use `internal_labels=True` for their inventory. `TDF_AttributeIterator` avoids the Python binding's unsafe missing-name output-handle lookup.

The report uses `instancing_method: assembly_occurrences`, `shared_instances_created`, and `assembly.occurrences`. The legacy `mapped_instances_created` field is zero. Product prototype counts and physical instance counts are different measurements.

For SolidWorks compatibility claims, run `scripts/verify_solidworks.py INPUT --report NEW_REPORT.json`. It imports an isolated copy with unique temporary product names into the already running application. It counts leaf solid bodies and compares shared occurrence transforms against STEPCAF. Preserve existing documents and settings, close only verification documents, and restore prior activation. A successful Open CASCADE import alone cannot establish this result. The three-pin assembly regression retained three solids at x = 0, 5 and 10 mm in SolidWorks; the corresponding mapped variants retained one. The full Envisense regression retained 164 bodies in 27 original component placements and matched all 54 shared occurrence transforms.

Do not compare rotated axis-aligned body boxes as if they were tight world bounds. SolidWorks `GetBodyBox` is approximate, and rotating a box around curved geometry overestimates its envelope. Compare the actual occurrence rotation and translation for pin placement; the verifier requires rotation matrix differences below 1e-8 and translations below 1e-5 mm. Avoid collecting every face COM object merely to count bodies.

Publish after source freshness, no-growth and geometry checks. Inputs containing mapped items or the helper's internal shared-product profile remain rejected pending a dedicated input adapter. Use the original direct-BRep export for a new cleanup.

## Confirmed Envisense result, 2026-10-16

The user confirmed `envisense_v3_cleaned.stp` worked after the full default cleanup and the SolidWorks import checks. This confirmation applies to the assembly-occurrence implementation, native microphone-hole recovery, and selective transplantation of changed bodies. It supersedes the earlier mapped-item attempts on this board.

| Measurement | Verified result |
| --- | --- |
| STEP bytes | 5,871,435 → 4,312,686 |
| Filled hole instances | 146, including the microphone's 0.15 mm and 0.25 mm bores |
| Selected component removals | 51 `R_` and 29 `CC_` occurrences |
| Retained original component placements | 27 |
| Physical solids in STEPCAF and SolidWorks | 164 |
| Stored solid geometries | 149 → 124 |
| Duplicate definitions replaced with shared references | 25 |
| Shared child placements checked in SolidWorks | 54, with maximum translation error below 1e-10 mm |

The output SHA-256 is `dca9cc234d36ed515d5ea80070a540527cd950bc11ba591f6165ce0a5fd0ad3a`. The adjacent `.cleanup.json` records the operations and native boundary proof; `.solidworks.json` records the successful import and placement checks against the same hash. These counts describe this artifact and are not acceptance constants for other boards. All 15 bundled regression tests passed before user confirmation.
