"""Regression coverage for schema extensions and partially successful defeaturing."""

import json
import logging
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from modules.step_graph import StepGraph, references, remapReferences
from step_cleanup import runCleanup


class SchemaAndDiagnosticsTests(unittest.TestCase):
	def testCheckFailureRetainsOtherFindings(self) -> None:
		import cadquery as cq
		from modules.cad_geometry import HoleRemovalError, HoleRemover
		from modules.cleanup_diagnostics import saveHoleFailure

		block = cq.Workplane("XY").box(10, 10, 2).val()
		original = block.cut(cq.Solid.makeCylinder(0.125, 2, (0, 0, -1)))
		with patch.object(HoleRemover, "flatBoard", return_value=block), patch.object(type(original), "cut", side_effect=RuntimeError("material comparison failed")):
			with self.assertRaises(HoleRemovalError) as captured:
				HoleRemover(0.8).edit(original)
		details = captured.exception.details
		self.assertTrue(details["checks"]["valid"])
		self.assertTrue(details["checks"]["selected_bores_absent"])
		self.assertIsNone(details["checks"]["original_material_preserved"])
		self.assertIn("material comparison failed", details["check_errors"]["original_material_preserved"])
		self.assertFalse(details["accepted"])
		with tempfile.TemporaryDirectory() as temporary:
			with patch.object(cq.exporters, "export", side_effect=RuntimeError("diagnostic export failed")):
				result = saveHoleFailure(captured.exception, Path(temporary) / "failed_part", False)
			self.assertEqual(len(result["artifact_errors"]), 3)
			self.assertTrue((Path(temporary) / "failed_part" / "bores.json").is_file())
			self.assertEqual(str(captured.exception), "Hole removal rejected: ['original_material_preserved']; remaining bore diameters mm=[]")

	def extendedFixture(self, source: Path) -> None:
		import cadquery as cq
		from modules.instancing_plan import InstancingPlanner

		shape = cq.Workplane("XY").box(10, 10, 10).val().cut(cq.Workplane("XY").box(2, 2, 2).val())
		assembly = cq.Assembly(name="Void assembly")
		assembly.add(shape, name="Void_A")
		assembly.add(shape.copy(), name="Void_B")
		assembly.export(str(source))
		graph = StepGraph(source)
		planner = InstancingPlanner(graph)
		for roots in graph.productSolids().values():
			plane_id = next(entity_id for entity_id in sorted(graph.closure(set(roots))) if graph.entities[entity_id].startswith("PLANE("))
			placement = graph.entities[references(graph.entities[plane_id])[0]]
			point_id, axis_z_id, axis_x_id = references(placement)
			axis_z = planner.points[axis_z_id][1]
			axis_x = planner.points[axis_x_id][1]
			axis_y = tuple(axis_z[(index + 1) % 3] * axis_x[(index + 2) % 3] - axis_z[(index + 2) % 3] * axis_x[(index + 1) % 3] for index in range(3))
			next_id = max(graph.entities) + 1
			graph.entities[next_id] = f"VECTOR('',#{axis_x_id},1.)"
			graph.entities[next_id + 1] = f"LINE('',#{point_id},#{next_id})"
			graph.entities[next_id + 2] = f"DIRECTION('',({','.join(str(value) for value in axis_y)}))"
			graph.entities[next_id + 3] = f"VECTOR('',#{next_id + 2},1.)"
			graph.entities[plane_id] = f"SURFACE_OF_LINEAR_EXTRUSION('',#{next_id + 1},#{next_id + 3})"
		graph.write(source)

	def testExtendedSchemaRoundtripPruningTransplantAndInstancing(self) -> None:
		from modules.cad_geometry import CadModel
		from modules.instancing_audit import compareInventories, worldInventory

		with tempfile.TemporaryDirectory() as temporary:
			work = Path(temporary)
			source = work / "extended.step"
			self.extendedFixture(source)
			original = source.read_bytes()
			graph = StepGraph(source)
			schema = graph.schemaInventory()
			self.assertFalse(schema["unsupported_families"])
			for family in ["BREP_WITH_VOIDS", "ORIENTED_CLOSED_SHELL", "SURFACE_OF_LINEAR_EXTRUSION"]:
				self.assertGreater(schema["families"][family]["count"], 0)
			before = CadModel(source)
			inventory = before.inventory(0.8)
			self.assertEqual(set(graph.productSolids()), set(before.parts))
			self.assertTrue(all(record["solids"] == 1 for record in inventory.values()))
			self.assertTrue(all(abs(record["volume"] - 992) < 1e-5 for record in inventory.values()))
			graph.prune(())
			for entity_id, value in graph.entities.items():
				self.assertEqual(value, graph.original_entities[entity_id])
			# Transplant a void solid and its full inner-shell/surface closure.
			donor = StepGraph(source)
			products = graph.productSolids()
			graph.transplant(donor, {products["Void_A"][0]: products["Void_B"][0]})
			graph.prune(())
			transplanted = work / "transplanted.step"
			graph.write(transplanted)
			compareInventories(worldInventory(before), worldInventory(CadModel(transplanted)))
			output = work / "cleaned.step"
			report = runCleanup(transplanted, output, 0.0, (), False)
			self.assertEqual(report["deduplication"]["solid_definitions_analyzed"], 2)
			self.assertEqual(report["deduplication"]["shared_instances_created"], 1)
			self.assertEqual(report["deduplication"]["physical_solids"], 2)
			self.assertEqual(source.read_bytes(), original)
			# Remove the void owners while retaining an independent unrelated product.
			import cadquery as cq
			kept_path = work / "unrelated.step"
			cq.exporters.export(cq.Workplane("XY").box(1, 2, 3).val(), str(kept_path))
			kept = StepGraph(kept_path)
			removed = StepGraph(source)
			next_id = max(removed.entities) + 1
			mapping = {entity_id: next_id + index for index, entity_id in enumerate(kept.entities)}
			kept_entities = {mapping[entity_id]: remapReferences(value, mapping) for entity_id, value in kept.entities.items()}
			removed.entities.update(kept_entities)
			removed.prune(("Void_",))
			remaining_schema = removed.schemaInventory()["families"]
			for family in ["BREP_WITH_VOIDS", "ORIENTED_CLOSED_SHELL", "SURFACE_OF_LINEAR_EXTRUSION"]:
				self.assertNotIn(family, remaining_schema)
			for entity_id, value in kept_entities.items():
				if entity_id in removed.entities:
					self.assertEqual(removed.entities[entity_id], value)
			self.assertEqual(len(removed.productSolids()), 1)
			removed_path = work / "removed.step"
			removed.write(removed_path)
			self.assertAlmostEqual(next(iter(CadModel(removed_path).parts.values())).Volume(), 6)

	def testUnknownFamilyInspectionAndFailureEvidence(self) -> None:
		import cadquery as cq

		with tempfile.TemporaryDirectory() as temporary:
			work = Path(temporary)
			source = work / "unknown.step"
			cq.exporters.export(cq.Workplane("XY").box(1, 2, 3).val(), str(source))
			graph = StepGraph(source)
			unknown_id = max(graph.entities) + 1
			graph.entities[unknown_id] = "UNFAMILIAR_METADATA('review me',#1)"
			plane_id = next(entity_id for entity_id, value in graph.entities.items() if value.startswith("PLANE("))
			graph.entities[plane_id] = graph.entities[plane_id].replace("PLANE(", "UNFAMILIAR_SURFACE(", 1)
			graph.write(source)
			original = source.read_bytes()
			command = [sys.executable, str(SCRIPTS / "step_cleanup.py"), str(source), "--inspect-schema"]
			result = subprocess.run(command, capture_output=True, text=True)
			self.assertEqual(result.returncode, 0, result.stderr)
			inspection = json.loads(result.stdout)
			self.assertEqual(inspection["unsupported_families"], ["UNFAMILIAR_METADATA", "UNFAMILIAR_SURFACE"])
			self.assertEqual(inspection["families"]["UNFAMILIAR_METADATA"]["samples"][0]["id"], unknown_id)
			self.assertTrue(inspection["families"]["UNFAMILIAR_SURFACE"]["samples"][0]["referenced_by"])
			output = work / "rejected.step"
			with self.assertRaisesRegex(ValueError, "Unsupported STEP record families"):
				runCleanup(source, output, 0.8, (), False)
			report = json.loads(next(work.glob("rejected.step.failed.*/failure.json")).read_text())
			self.assertEqual(report["stage"], "schema")
			self.assertEqual(report["findings"]["schema"], inspection)
			self.assertTrue(report["source_unchanged"])
			self.assertFalse(output.exists())
			self.assertEqual(source.read_bytes(), original)
			cli_output = work / "cli_rejected.step"
			result = subprocess.run([*command[:-1], "--output", str(cli_output)], capture_output=True, text=True)
			self.assertEqual(result.returncode, 1, result.stderr)
			self.assertIn("failure.json", result.stderr)
			self.assertFalse(cli_output.exists())
			self.assertTrue(next(work.glob("cli_rejected.step.failed.*/failure.json")).is_file())

	def testDoneOperationWithOneBoreLeftRetainsDiagnostics(self) -> None:
		import cadquery as cq
		from modules.cad_geometry import CadModel, HoleRemovalError, HoleRemover, boreFaces, completeGroups

		block = cq.Workplane("XY").box(10, 10, 2).val()
		large_bore = cq.Solid.makeCylinder(0.125, 2, (-2, 0, -1))
		small_bore = cq.Solid.makeCylinder(0.075, 2, (2, 0, -1))
		original_shape = block.cut(large_bore).cut(small_bore)
		partial = block.cut(small_bore)
		class PartialOperation:
			def SetShape(self, shape: object) -> None:
				pass
			def SetRunParallel(self, enabled: bool) -> None:
				pass
			def AddFaceToRemove(self, face: object) -> None:
				pass
			def Build(self) -> None:
				pass
			def IsDone(self) -> bool:
				return True
			def HasWarnings(self) -> bool:
				return True
			def Shape(self) -> object:
				return partial.wrapped
		with tempfile.TemporaryDirectory() as temporary:
			work = Path(temporary)
			source = work / "two_bores.step"
			assembly = cq.Assembly(name="Main")
			# An earlier accepted part proves stage findings survive a later failure.
			assembly.add(block.cut(large_bore), name="Earlier_part")
			assembly.add(original_shape, name="SPV61A0LR5H-1")
			assembly.export(str(source))
			original_bytes = source.read_bytes()
			for in_place in [False, True]:
				output = source if in_place else work / "cleaned.step"
				with patch.object(HoleRemover, "flatBoard", return_value=None), patch("modules.cad_geometry.BRepAlgoAPI_Defeaturing", PartialOperation):
					# Earlier_part uses real editing; inject partial success only for the failing definition.
					original_edit = HoleRemover.edit
					def selectiveEdit(remover: HoleRemover, shape: cq.Shape) -> tuple[cq.Shape, int]:
						if len(completeGroups(boreFaces(shape, 0.8))) == 1:
							return block, 1
						return original_edit(remover, shape)
					with patch.object(HoleRemover, "edit", selectiveEdit), patch("modules.native_holes.repairNativeHoles", side_effect=ValueError("Native repair unavailable in this failure injection")):
						with self.assertRaises(HoleRemovalError):
							runCleanup(source, output, 0.8, (), in_place, diagnose_bores=in_place)
				failure_path = next(work.glob(f"{output.name}.failed.*/failure.json"))
				report = json.loads(failure_path.read_text())
				self.assertEqual(report["product"], "SPV61A0LR5H-1")
				self.assertEqual(report["stage"], "hole_removal")
				self.assertIn("hole_removal:Earlier_part", report["completed_stages"])
				bores = report["findings"]["failed_hole_operation"]
				self.assertTrue(bores["operation"]["is_done"])
				self.assertFalse(bores["checks"]["selected_bores_absent"])
				self.assertTrue(all(value for key, value in bores["checks"].items() if key != "selected_bores_absent"))
				self.assertEqual(sorted(round(bore["diameter_mm"], 2) for bore in bores["selected_bores"]), [0.15, 0.25])
				self.assertEqual([round(bore["diameter_mm"], 2) for bore in bores["remaining_bores"]], [0.15])
				self.assertTrue(bores["selected_face_indices"])
				self.assertFalse(bores["artifact_errors"])
				for name in ["original_part.stp", "rejected_part.stp", "selected_faces.stp", "bores.json"]:
					self.assertTrue((failure_path.parent / "failed_part" / name).is_file())
				self.assertTrue((failure_path.parent / "partial_assembly.stp").is_file())
				if in_place:
					trials = json.loads((failure_path.parent / "failed_part" / "trials.json").read_text())
					self.assertEqual(len(trials), 2)
					self.assertTrue(any(trial["status"] == "rejected" for trial in trials))
				else:
					self.assertFalse((failure_path.parent / "failed_part" / "trials.json").exists())
				self.assertTrue(CadModel(failure_path.parent / "failed_part" / "rejected_part.stp").inventory(0.8))
				self.assertTrue(report["source_unchanged"])
				self.assertFalse(report["published"])
				self.assertEqual(source.read_bytes(), original_bytes)
				if not in_place:
					self.assertFalse(output.exists())
				self.assertFalse(list(work.glob("*.cleanup*.json")))
				self.assertFalse(list(work.glob("*.bak")))


if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO, format="%(message)s")
	unittest.main()
