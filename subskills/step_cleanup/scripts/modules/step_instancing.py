"""Run the mandatory final cleanup stage against a private STEP candidate."""

import logging
import shutil
from pathlib import Path

from .cad_geometry import CadModel, boundsKey
from .instancing_audit import cadTransform, checkSharedReferences, compareInventories, digest, rigidTransform, uniqueGeometry, worldInventory, worldSolids
from .instancing_graph import AssemblyInstancing
from .instancing_plan import InstancingPlanner
from .step_graph import StepGraph

logger = logging.getLogger(__name__)


def deduplicateCandidate(source: Path, candidate: Path) -> dict:
	"""Write a checked candidate; publication/backup belongs to the calling CLI."""
	if candidate.exists() or source.resolve() == candidate.resolve():
		raise ValueError("Instancing candidate must be a new path distinct from its source")
	source_digest = digest(source)
	graph = StepGraph(source)
	graph.checkSupported()
	if any(value.startswith(("MAPPED_ITEM(", "PRODUCT('__STEP_SHARED_")) for value in graph.entities.values()):
		raise ValueError("Input already contains mapped or assembly-instanced geometry; use the original direct-BRep export for this helper")
	plan = InstancingPlanner(graph).plan()
	model = CadModel(source)
	logger.info("Auditing source geometry and inherited face appearances")
	before = worldInventory(model)
	source_geometry_count = uniqueGeometry(worldSolids(model))
	aliases = []
	part_solids = {}
	for name, shape in model.parts.items():
		part_solids[name] = {}
		for solid in shape.Solids():
			key = boundsKey(solid)
			if key in part_solids[name]:
				raise ValueError(f"Ambiguous solid correspondence in {name}")
			part_solids[name][key] = solid

	def sourceSolid(record: dict) -> object:
		# Low-level entityShape fallback may return an unhealed, invalid pin.
		# Use it only to associate bounds with valid solids from the full import.
		key = boundsKey(model.entityShape(record["root"]))
		shape = part_solids[record["name"]][key]
		if not shape.isValid():
			raise ValueError(f"Invalid fully imported source solid #{record['root']}")
		return shape

	if plan["shared_groups"]:
		instancer = AssemblyInstancing(graph)
		for group in plan["shared_groups"]:
			canonical = min(group, key=lambda item: item["root"])
			canonical_shape = sourceSolid(canonical)
			for duplicate in group:
				if duplicate["root"] == canonical["root"]:
					continue
				rotation, translation = rigidTransform(canonical, duplicate)
				original = sourceSolid(duplicate)
				placed = canonical_shape.moved(cadTransform(rotation, translation))
				if boundsKey(original) != boundsKey(placed) or len(original.Faces()) != len(placed.Faces()):
					raise ValueError(f"Rigid placement mismatch for solid #{duplicate['root']}")
				missing = original.cut(placed).Volume()
				extra = placed.cut(original).Volume()
				if missing > 1e-6 or extra > 1e-6:
					raise ValueError(f"Geometry mismatch for #{duplicate['root']}: missing={missing}, extra={extra}")
				aliases.append({"root": duplicate["root"], "component": duplicate["name"],
					"prototype": canonical["root"], "prototype_component": canonical["name"],
					"rotation": rotation, "translation": translation,
					"missing_volume_mm3": missing, "extra_volume_mm3": extra})
				if len(aliases) % 25 == 0:
					logger.info("Verified and instanced %d / %d duplicate solids", len(aliases), plan["solid_definitions"] - plan["prototype_count"])
		assembly = instancer.apply(aliases)
		compaction = graph.prune(())
		graph.write(candidate)
	else:
		# A mandatory stage can validly find no matches. Preserve the file exactly.
		compaction = {"discarded_records": 0}
		assembly = {"occurrences": [], "prototypes": 0}
		shutil.copy2(source, candidate)
	final_graph = StepGraph(candidate)
	checkSharedReferences(StepGraph(source), final_graph, aliases, assembly)
	logger.info("Reopening instanced candidate to check geometry, colors, and sharing")
	final_model = CadModel(candidate, internal_labels=True)
	after = worldInventory(final_model)
	compareInventories(before, after)
	geometry_count = uniqueGeometry(worldSolids(final_model))
	if aliases and geometry_count >= source_geometry_count:
		raise ValueError("CAD reader did not actually share the mapped geometry")
	if not aliases and geometry_count != source_geometry_count:
		raise ValueError("Stored geometry count changed without a mapped replacement")
	for entity_id, value in graph.original_entities.items():
		if value.startswith(("PRODUCT(", "PRODUCT_DEFINITION(", "SHAPE_DEFINITION_REPRESENTATION(", "NEXT_ASSEMBLY_USAGE_OCCURRENCE(", "ITEM_DEFINED_TRANSFORMATION(")):
			if final_graph.entities.get(entity_id) != value:
				raise ValueError(f"Product/placement metadata changed at #{entity_id}")
	if digest(source) != source_digest or candidate.stat().st_size > source.stat().st_size:
		raise ValueError("Instancing source changed, or candidate grew in size")
	report = {"source_sha256": source_digest, "output_sha256": digest(candidate),
		"input_bytes": source.stat().st_size, "output_bytes": candidate.stat().st_size,
		"solid_definitions_analyzed": plan["solid_definitions"], "shared_groups": len(plan["shared_groups"]),
		"stored_solids_before": source_geometry_count, "stored_solids_after": geometry_count,
		"mapped_instances_created": 0, "shared_instances_created": len(aliases),
		"instancing_method": "assembly_occurrences", "assembly": assembly, "named_assembly_roots": len(after),
		"physical_solids": sum(record["solids"] for record in after.values()),
		"all_geometry_checks_passed": True, "face_appearance_checks_passed": True,
		"shared_reference_checks_passed": True,
		"product_and_placement_metadata_preserved": True, "compaction": compaction,
		"aliases": aliases, "application_validation": "not performed by helper"}
	logger.info("Instancing passed: %d -> %d stored geometries, %d shared instances, %d -> %d bytes",
		source_geometry_count, geometry_count, len(aliases), report["input_bytes"], report["output_bytes"])
	return report
