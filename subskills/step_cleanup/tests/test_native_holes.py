"""Regression coverage for native hole repair and unchanged package bodies."""

import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from step_cleanup import runCleanup
from modules.cad_geometry import CadModel, HoleRemover
from modules.step_graph import StepGraph


class NativeHoleTests(unittest.TestCase):
	def testNativeFallbackRepairsMissedBlindBore(self) -> None:
		import cadquery as cq
		with tempfile.TemporaryDirectory() as temporary:
			work = Path(temporary)
			block = cq.Workplane("XY").box(4, 4, 2).val()
			shape = block.cut(cq.Solid.makeCylinder(0.075, 0.05, (0, 0, 0.95)))
			assembly = cq.Assembly(name="Main")
			assembly.add(shape, name="Microphone", color=cq.Color(0.5, 0.6, 0.7))
			source = work / "source.step"
			assembly.export(str(source))
			original = source.read_bytes()
			with patch.object(HoleRemover, "defeature", side_effect=lambda shape, selected: (shape, {"is_done": True})):
				report = runCleanup(source, work / "cleaned.step", 0.8, (), False)
			proof = report["hole_changes"]["Microphone"]["native_repair"]
			self.assertTrue(proof["native_boundary_proof_passed"])
			self.assertTrue(proof["area_check_passed"])
			self.assertAlmostEqual(proof["cavity_volume_mm3"], math.pi * 0.075 ** 2 * 0.05)
			self.assertEqual(report["hole_instances_filled"], 1)
			self.assertEqual(source.read_bytes(), original)
			self.assertFalse(CadModel(work / "cleaned.step").inventory(0.8)["Microphone"]["small_holes"])

	def testPackageEditPreservesNativePinRecords(self) -> None:
		import cadquery as cq
		from modules.cad_geometry import boreFaces, completeGroups

		with tempfile.TemporaryDirectory() as temporary:
			work = Path(temporary)
			body = cq.Workplane("XY").box(4, 4, 2).val().cut(cq.Solid.makeCylinder(0.1, 0.3, (0, 0, 0.7)))
			pins = [cq.Workplane("XY").box(0.2, 0.3, height).val().translate((offset, 0, -1.5)) for offset, height in ((-1, 1), (1, 1.2))]
			assembly = cq.Assembly(name="Main")
			assembly.add(cq.Compound.makeCompound([body, *pins]), name="Package", color=cq.Color(0.2, 0.4, 0.6))
			source = work / "package.step"
			assembly.export(str(source))
			graph = StepGraph(source)
			model = CadModel(source)
			pin_roots = [root for root in graph.productSolids()["Package"] if not completeGroups(boreFaces(model.entityShape(root), 0.8))]
			pin_records = {entity_id: graph.entities[entity_id] for root in pin_roots for entity_id in graph.closure({root})}
			output = work / "cleaned.step"
			report = runCleanup(source, output, 0.8, (), False)
			self.assertEqual(report["hole_changes"]["Package"]["edited_solids"], 1)
			self.assertEqual(report["hole_changes"]["Package"]["preserved_solids"], 2)
			final = StepGraph(output)
			for entity_id, value in pin_records.items():
				self.assertEqual(final.entities[entity_id], value)
			self.assertEqual(report["remaining_solids"], 3)


if __name__ == "__main__":
	unittest.main()
