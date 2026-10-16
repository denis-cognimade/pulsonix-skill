# Extending the STEP profile

## Inspect before changing the supported set

Run `step_cleanup.py INPUT --inspect-schema > schema.json`. This reads the graph without CAD startup and makes no edits. Save the input hash with the inspection. The inventory reports counts and three samples per family with references and incoming referrers. For a family whose samples do not describe all uses, inspect every occurrence with `StepGraph.entities`, `references()` and `closure()`; samples are not a schema validator. Complex records are listed as `<complex>`; that label is an inventory category, not evidence that an unfamiliar complex declaration is supported.

Build a small fixture from the failing geometry family, preserving the relevant relationships. Use synthetic geometry in committed tests when the original board cannot be redistributed. Record the actual failing product and record IDs in the diagnostic report. Do not modify the only original file to experiment with a schema change.

## Classify by semantics

Use the applicable EXPRESS schema or the implementing kernel's source to determine inherited attributes, reference roles and inverse relationships. A record can be:

| Role | Required change |
| --- | --- |
| Geometry dependency, reached through an existing retained solid | Preserve its native record and walk all forward dependencies; prove pruning and transplantation preserve its meaning. |
| New solid subtype or representation item | Update product-to-solid enumeration, correspondence checks, instancing representation lookup and any subtype assumptions, as well as the supported set. Prove the reader imports every root. |
| Semantic root or inverse metadata relationship (materials, PMI, layers, approvals) | Add explicit retention/removal semantics and tests. Forward reachability from geometry alone can discard meaningful records. |
| New assembly, placement, units or mapped-representation layout | Implement a dedicated adapter with identity, transform, unit and appearance checks. An allowlist entry cannot establish these semantics. |

If a family has mixed roles, handle every role before supporting it. Do not preserve all unknown records as roots: they can keep removed products and obsolete geometry live. Do not ignore unknown records: they can contain retained metadata. Leave unsupported cases rejected with inspection evidence.

## Implemented extension: void solids and extruded surfaces

- `BREP_WITH_VOIDS(name, outer, voids)` is a subtype of `MANIFOLD_SOLID_BREP`, with an outer closed shell and a nonempty set of oriented inner shells. It is a direct solid root. `SOLID_PREFIXES` is shared by product enumeration and native instancing so these solids are counted, transplanted and deduplicated. Both outer and inner dependency closures must survive until their owning solid is removed or replaced.
- `ORIENTED_CLOSED_SHELL(name, *, closed_shell_element, orientation)` is an oriented shell dependency. Preserve the derived-attribute marker and orientation exactly; treating its referenced cavity shell as an independent solid would change material.
- `SURFACE_OF_LINEAR_EXTRUSION(name, swept_curve, extrusion_axis)` is a surface dependency. Preserve both the curve and vector (including its magnitude); do not replace it with an analytic plane or cylinder merely because a sample looks similar.

Schema sources: [BREP_WITH_VOIDS](https://downloads.steptools.com/docs/stp_aim/html/t_brep_with_voids.html), [ORIENTED_CLOSED_SHELL](https://downloads.steptools.com/docs/stp_aim/html/t_oriented_closed_shell.html), [SURFACE_OF_LINEAR_EXTRUSION](https://www.steptools.com/stds/stp_aim/html/t_surface_of_linear_extrusion.html). Check the source file's declared schema when adapting another export profile.

## Required evidence before accepting an extension

1. Add a fixture that contains the real family and valid relationships, not merely an unused textual entity. The bundled fixture has a closed box cavity and a face represented as a surface of linear extrusion. Two independent definitions allow the final instancing path to be exercised.
2. Import with the pinned CadQuery/Open CASCADE environment and verify valid physical solids, expected cavity volume, bounds and product/solid correspondence. A parser roundtrip alone is insufficient.
3. Prune without selection and prove retained native record values and required closures remain unchanged. Remove a selected owner and prove its unused topology disappears while unrelated owners, occurrences and styles survive.
4. Transplant an edited or equivalent donor solid using explicit root correspondence, prune again, then reimport. Verify inner shells, surfaces, geometry, product identities, placements and relevant appearance.
5. Run the mandatory deduplication path on matching definitions with the new family. Verify stored geometry decreases, placed solid count and cavity volume remain correct, and the reader actually shares topology. Also test a nonmatching case where appropriate.
6. Keep a genuinely unsupported family in tests. Inspection must name it and show record IDs/references; cleanup must fail before publication, retain the schema findings and leave source bytes unchanged.
7. Run all suites documented in `SKILL.md`. State the tested fixture/profile and distinguish kernel checks from Pulsonix or SolidWorks validation. Do not broaden the supported profile based only on the presence of names in `KNOWN_TYPES`.
