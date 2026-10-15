"""Behavioral coverage for mandatory STEP geometry instancing."""

import hashlib
import logging
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from step_cleanup import runCleanup
from step_deduplicate import runDeduplication


class InstancingTests(unittest.TestCase):
	def testCliValidation(self) -> None:
		command = [sys.executable, str(SCRIPTS / "step_deduplicate.py")]
		for argument in ["--help", "--version"]:
			self.assertEqual(subprocess.run([*command, argument], capture_output=True).returncode, 0)
		self.assertEqual(subprocess.run([*command, "missing.step"], capture_output=True).returncode, 2)

	def testMandatoryInstancingPreservesColorAndPlacement(self) -> None:
		import cadquery as cq
		from modules.cad_geometry import CadModel
		from modules.instancing_audit import compareInventories, worldInventory, worldSolids
		from modules.instancing_plan import InstancingPlanner
		from modules.step_graph import StepGraph

		with tempfile.TemporaryDirectory() as temporary:
			work = Path(temporary)
			box = cq.Workplane("XY").box(2, 4, 6).val()
			assembly = cq.Assembly(name="Testing")
			assembly.add(box, name="Part_A", color=cq.Color(0.3, 0.5, 0.7))
			assembly.add(box.rotate((0, 0, 0), (0, 0, 1), 90).translate((10, 5, 2)),
				name="Part_B", color=cq.Color(0.3, 0.5, 0.7))
			assembly.add(box.translate((20, 0, 0)), name="Part_C", color=cq.Color(0.9, 0.1, 0.2))
			source = work / "source.step"
			assembly.export(str(source))
			# Keep the native topology ordering/parameterization identical while
			# applying an exact 90-degree transform to the second definition.
			# Independent CAD re-exports can reparameterize this same box.
			graph = StepGraph(source)
			donor = StepGraph(source)
			products = graph.productSolids()
			planner = InstancingPlanner(donor)
			for entity_id in donor.closure({products["Part_A"][0]}):
				if entity_id in planner.points:
					kind, (x, y, z) = planner.points[entity_id]
					values = (-y, x, z)
					if kind == "CARTESIAN_POINT":
						values = tuple(first + second for first, second in zip(values, (10, 5, 2)))
					donor.entities[entity_id] = f"{kind}('',({','.join(str(value) for value in values)}))"
			graph.transplant(donor, {products["Part_A"][0]: products["Part_B"][0]})
			graph.prune(())
			graph.write(source)
			source_bytes = source.read_bytes()
			before = worldInventory(CadModel(source))
			output = work / "cleaned.step"
			report = runCleanup(source, output, 0.0, (), False)
			instancing = report["deduplication"]
			self.assertEqual(instancing["mapped_instances_created"], 1)
			self.assertEqual(instancing["stored_solids_before"], 3)
			self.assertEqual(instancing["stored_solids_after"], 2)
			self.assertEqual(instancing["physical_solids"], 3)
			model = CadModel(output, internal_labels=True)
			compareInventories(before, worldInventory(model))
			solids = worldSolids(model)
			self.assertTrue(solids[0].wrapped.IsPartner(solids[1].wrapped))
			self.assertFalse(solids[0].wrapped.IsPartner(solids[2].wrapped))
			self.assertEqual(source.read_bytes(), source_bytes)
			self.assertLess(output.stat().st_size, len(source_bytes))
			original_graph = StepGraph(source)
			final_graph = StepGraph(output)
			for entity_id, value in original_graph.entities.items():
				if value.startswith(("PRODUCT(", "PRODUCT_DEFINITION(", "NEXT_ASSEMBLY_USAGE_OCCURRENCE(", "ITEM_DEFINED_TRANSFORMATION(")):
					self.assertEqual(final_graph.entities[entity_id], value)
			with self.assertRaisesRegex(ValueError, "already contains mapped geometry"):
				runDeduplication(output, work / "twice.step")
			self.assertFalse((work / "twice.step").exists())

	def testNoMatchesIsSuccessfulAndDoesNotGrow(self) -> None:
		import cadquery as cq

		with tempfile.TemporaryDirectory() as temporary:
			work = Path(temporary)
			source = work / "unique.step"
			cq.exporters.export(cq.Workplane("XY").box(2, 4, 6).val(), str(source))
			digest = hashlib.sha256(source.read_bytes()).hexdigest()
			output = work / "checked.step"
			report = runDeduplication(source, output)
			self.assertEqual(report["mapped_instances_created"], 0)
			self.assertEqual(report["stored_solids_before"], report["stored_solids_after"])
			self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), digest)
			with self.assertRaisesRegex(ValueError, "new output path"):
				runDeduplication(source, output)


if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
	unittest.main()
