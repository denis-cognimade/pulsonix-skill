"""Clean a supported PCB STEP export without rewriting unrelated geometry."""

import argparse
import hashlib
import json
import logging
import math
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def digest(path: Path) -> str:
	return hashlib.sha256(path.read_bytes()).hexdigest()


def runCleanup(source: Path, output: Path, diameter: float, prefixes: tuple[str, ...], in_place: bool, diagnose_bores: bool = False) -> dict:
	from modules.cleanup_diagnostics import CleanupDiagnostics, saveHoleFailure
	from modules.step_graph import StepGraph

	if not in_place and (source.resolve() == output.resolve() or output.exists()):
		raise ValueError("Choose a new output path distinct from the source")
	if in_place and source.resolve() != output.resolve():
		raise ValueError("In-place cleanup requires output to equal source")
	source_digest = digest(source)
	report_path = output.with_suffix(f"{output.suffix}.cleanup.json")
	if report_path.exists():
		if in_place:
			report_path = output.with_suffix(f"{output.suffix}.cleanup.{uuid.uuid4().hex[:8]}.json")
		else:
			raise ValueError(f"Report already exists: {report_path}; choose another output name")
	options = {"hole_diameter_mm": diameter, "remove_prefixes": list(prefixes), "in_place": in_place, "diagnose_bores": diagnose_bores}
	with tempfile.TemporaryDirectory(prefix=".step_cleanup_", dir=output.parent) as temporary, CleanupDiagnostics(source, output, Path(temporary), options) as diagnostics:
		work = Path(temporary)
		graph = StepGraph(source)
		diagnostics.report["findings"]["schema"] = graph.schemaInventory()
		diagnostics.checkpoint()
		graph.checkSupported()
		if any(value.startswith(("MAPPED_ITEM(", "PRODUCT('__STEP_SHARED_")) for value in graph.entities.values()):
			raise ValueError("Input already contains mapped or assembly-instanced geometry; run cleanup from the original direct-BRep export")
		diagnostics.passed("schema")
		# Keep schema inspection, --help and argument errors independent of CAD startup.
		import cadquery as cq
		from modules.cad_geometry import CadModel, HoleRemover, HoleRemovalError, boundsKey
		from modules.step_instancing import deduplicateCandidate
		diagnostics.stage("component_removal")
		component_report = graph.prune(prefixes)
		filtered_path = work / "components_filtered.stp"
		graph.write(filtered_path)
		diagnostics.passed("component_removal", component_report)
		diagnostics.stage("baseline_inventory")
		model = CadModel(filtered_path)
		baseline = model.inventory(diameter)
		expected = dict(baseline)
		instance_names = model.instanceNames()
		products = graph.productSolids()
		if set(products) != set(model.parts):
			raise ValueError("STEP solid products do not match CAD definitions; extend solid-root handling before editing")
		diagnostics.passed("baseline_inventory", {"inventory": baseline, "instances": dict(instance_names), "solid_roots": products})
		changes = {}
		diagnostics.report["findings"]["hole_changes"] = changes
		if diameter:
			remover = HoleRemover(diameter)
			for name, original in model.parts.items():
				if not baseline[name]["small_holes"]:
					continue
				logger.info("Filling %d small holes in %s", baseline[name]["small_holes"], name)
				diagnostics.stage("hole_removal", name)
				native_proof = None
				try:
					edited, count = remover.edit(original)
				except HoleRemovalError as error:
					try:
						from modules.native_holes import repairNativeHoles
						logger.info("CAD defeaturing rejected %s; checking native cylinder boundaries", name)
						edited, native_proof = repairNativeHoles(graph, model, name, diameter, work)
						count = native_proof["bores"]
					except Exception as native_error:
						error.details["native_repair_error"] = str(native_error)
						diagnostics.report["findings"]["failed_hole_operation"] = error.details
						diagnostics.checkpoint()
						try:
							diagnostics.report["findings"]["failed_hole_operation"] = saveHoleFailure(error, work / "failed_part", diagnose_bores)
						except Exception as diagnostic_error:
							diagnostics.report["findings"]["failed_hole_operation"] = {**error.details, "artifact_error": str(diagnostic_error)}
						raise error from native_error
				if native_proof is not None:
					expected[name] = {**baseline[name], "volume": edited.Volume(), "faces": len(edited.Faces()), "small_holes": 0}
					changes[name] = {"holes_per_definition": count, "instances": instance_names[name],
						"volume_added_mm3": native_proof["cavity_volume_mm3"], "native_repair": native_proof}
					graph.write(work / "partial_assembly.stp")
					diagnostics.passed(f"hole_removal:{name}", changes[name])
					continue
				# Preserve native topology and face styles on untouched bodies.
				original_solids = original.Solids()
				changed_solids = [solid for solid in edited.Solids()
					if not any(solid.wrapped.IsSame(before.wrapped) for before in original_solids)]
				if not changed_solids or len(edited.Solids()) != len(original_solids):
					raise ValueError(f"Invalid changed-solid inventory for {name}")
				donor_path = work / "edited_part.stp"
				cq.exporters.export(cq.Compound.makeCompound(changed_solids), str(donor_path), exportType="STEP")
				donor_graph = StepGraph(donor_path)
				donor_model = CadModel(donor_path)
				old_ids = products.get(name, [])
				new_ids = [entity_id for values in donor_graph.productSolids().values() for entity_id in values]
				if len(new_ids) != len(changed_solids) or len(old_ids) != len(original_solids):
					raise ValueError(f"Ambiguous solid correspondence for {name}")
				def solidMap(cad_model: CadModel, entity_ids: list[int]) -> dict:
					mapping = {}
					for entity_id in entity_ids:
						key = boundsKey(cad_model.entityShape(entity_id))
						if key in mapping:
							raise ValueError(f"Coincident solid bounds require explicit correspondence in {name}")
						mapping[key] = entity_id
					return mapping
				old_map = solidMap(model, old_ids)
				new_map = solidMap(donor_model, new_ids)
				if not new_map.keys() <= old_map.keys():
					raise ValueError(f"Edited solid placement changed in {name}")
				graph.transplant(donor_graph, {new_map[key]: old_map[key] for key in new_map})
				expected[name] = {**baseline[name], "volume": edited.Volume(), "faces": len(edited.Faces()), "small_holes": 0}
				changes[name] = {"holes_per_definition": count, "instances": instance_names[name],
					"edited_solids": len(changed_solids), "preserved_solids": len(original_solids) - len(changed_solids),
					"volume_added_mm3": edited.Volume() - original.Volume()}
				# Preserve a native assembly candidate containing all earlier accepted edits.
				graph.write(work / "partial_assembly.stp")
				diagnostics.passed(f"hole_removal:{name}", changes[name])
		diagnostics.stage("compaction")
		compaction_report = graph.prune(())
		candidate = work / "validated_candidate.stp"
		graph.write(candidate)
		diagnostics.passed("compaction", compaction_report)
		diagnostics.stage("geometry_roundtrip")
		logger.info("Reopening candidate for final geometry verification")
		final_model = CadModel(candidate)
		actual = final_model.inventory(diameter)
		diagnostics.report["findings"]["geometry_roundtrip_actual"] = actual
		if actual.keys() != expected.keys() or final_model.instanceNames() != instance_names:
			raise ValueError("Component definitions or retained instance counts changed unexpectedly")
		for name, record in actual.items():
			diagnostics.report["product"] = name
			before = expected[name]
			for key in ["solids", "faces", "bounds", "protected_holes", "small_holes"]:
				if record[key] != before[key]:
					raise ValueError(f"Verification failed for {name}: {key}")
			if abs(record["volume"] - before["volume"]) > 1e-5:
				raise ValueError(f"Verification failed for {name}: volume changed")
		diagnostics.passed("geometry_roundtrip", actual)
		# Deduplication is the mandatory final stage, after hole/component checks.
		instanced_candidate = work / "instanced_candidate.stp"
		diagnostics.stage("deduplication")
		instancing_report = deduplicateCandidate(candidate, instanced_candidate)
		diagnostics.passed("deduplication", instancing_report)
		candidate = instanced_candidate
		diagnostics.stage("publication")
		if candidate.stat().st_size > source.stat().st_size:
			raise ValueError("Candidate grew in size; inspect retained records before publishing cleanup")
		if digest(source) != source_digest:
			raise ValueError("Source changed during cleanup; refusing to publish a stale result")
		candidate_digest = digest(candidate)
		report = {"source": str(source), "output": str(output), "source_sha256": source_digest,
			"output_sha256": candidate_digest, "input_bytes": source.stat().st_size,
			"output_bytes": candidate.stat().st_size, "hole_diameter_mm": diameter,
			"remove_prefixes": list(prefixes), "components": component_report,
			"compaction": compaction_report, "hole_changes": changes,
			"hole_instances_filled": sum(change["holes_per_definition"] * change["instances"] for change in changes.values()),
			"remaining_definitions": len(actual), "remaining_instances": sum(instance_names.values()),
			"remaining_solids": sum(instance_names[name] * record["solids"] for name, record in actual.items()),
			"deduplication": instancing_report,
			"roundtrip_valid": True, "dangling_references": 0}
		if in_place:
			backup = source.with_name(f"{source.name}.step_cleanup.{uuid.uuid4().hex[:8]}.bak")
			shutil.copy2(source, backup)
			if digest(backup) != source_digest:
				raise ValueError("Source backup hash verification failed")
			report["backup"] = str(backup)
		elif output.exists():
			raise ValueError(f"Output appeared during cleanup: {output}")
		if digest(source) != source_digest:
			raise ValueError("Source changed before publication")
		report_temporary = work / "report.json"
		report_temporary.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
		os.replace(candidate, output)
		diagnostics.report["published"] = True
		os.replace(report_temporary, report_path)
		logger.info("Published %s (%d -> %d bytes); report %s", output, report["input_bytes"], report["output_bytes"], report_path)
		return report


def main() -> int:
	parser = argparse.ArgumentParser(description="Fill small holes, remove named PCB components, prune obsolete STEP records, and deduplicate shared geometry.")
	parser.add_argument("--version", action="version", version="step_cleanup 1.3.0")
	parser.add_argument("source", type=Path, help="Input .stp or .step file")
	output_options = parser.add_mutually_exclusive_group()
	output_options.add_argument("--output", type=Path, help="New output path; default SOURCE_cleaned.stp")
	output_options.add_argument("--in-place", action="store_true", help="Replace source after validation and a verified backup")
	parser.add_argument("--hole-diameter", type=float, default=0.8, help="Fill circular holes strictly below this diameter in mm (default 0.8)")
	parser.add_argument("--keep-holes", action="store_true", help="Skip hole removal")
	parser.add_argument("--inspect-schema", action="store_true", help="Write schema inventory JSON to stdout without CAD import or editing")
	parser.add_argument("--diagnose-bores", action="store_true", help="On hole failure, also run independent per-bore diagnostic trials (can be slow)")
	component_options = parser.add_mutually_exclusive_group()
	component_options.add_argument("--remove-prefix", action="append", help="Case-sensitive product prefix; repeat for several (default R_ and CC_)")
	component_options.add_argument("--keep-components", action="store_true", help="Skip named component removal")
	args = parser.parse_args()
	source = args.source.resolve()
	output = source if args.in_place else (args.output.resolve() if args.output else source.with_name(f"{source.stem}_cleaned{source.suffix}"))
	if not source.is_file() or source.suffix.lower() not in {".stp", ".step"}:
		parser.error("source must be an existing .stp or .step file")
	if args.inspect_schema:
		if args.output or args.in_place:
			parser.error("--inspect-schema cannot be combined with --output or --in-place")
		try:
			from modules.step_graph import StepGraph
			sys.stdout.write(f"{json.dumps(StepGraph(source).schemaInventory(), indent=2)}\n")
			return 0
		except Exception as error:
			parser.exit(1, f"Schema inspection failed: {error}\n")
	if not math.isfinite(args.hole_diameter) or args.hole_diameter <= 0:
		parser.error("--hole-diameter must be a finite positive number")
	if output.suffix.lower() not in {".stp", ".step"} or not output.parent.is_dir():
		parser.error("output must be a .stp/.step path in an existing directory")
	if not args.in_place and (output == source or output.exists()):
		parser.error("output already exists or equals source; use a new path, or --in-place for the source")
	if args.remove_prefix and any(not prefix for prefix in args.remove_prefix):
		parser.error("--remove-prefix cannot be empty")
	prefixes = () if args.keep_components else tuple(args.remove_prefix or ["R_", "CC_"])
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
	try:
		runCleanup(source, output, 0.0 if args.keep_holes else args.hole_diameter, prefixes, args.in_place, args.diagnose_bores)
		return 0
	except KeyboardInterrupt:
		logger.error("Cleanup interrupted; no unvalidated STEP was published")
		return 130
	except Exception as error:
		logger.error("Cleanup failed: %s", error)
		return 1


if __name__ == "__main__":
	raise SystemExit(main())
