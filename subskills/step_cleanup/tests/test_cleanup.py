import logging
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from modules.step_graph import StepGraph, remapReferences, references
from step_cleanup import runCleanup


class CleanupTests(unittest.TestCase):
	def testQuotedStepText(self) -> None:
		with tempfile.TemporaryDirectory() as temporary:
			path = Path(temporary) / "quoted.step"
			path.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n#1 = PRODUCT('R_#999;it''s','R_#999;it''s','',(#2));\n#2 = PRODUCT_CONTEXT('',#3,'mechanical');\n#3 = APPLICATION_CONTEXT('mechanical');\nENDSEC;\nEND-ISO-10303-21;\n", encoding="utf-8")
			graph = StepGraph(path)
			self.assertEqual(references(graph.entities[1]), [2])
			remapped = remapReferences(graph.entities[1], {2: 42})
			self.assertIn("R_#999;it''s", remapped)
			self.assertEqual(references(remapped), [42])
			graph.write(Path(temporary) / "roundtrip.step")

	def testCliValidation(self) -> None:
		command = [sys.executable, str(SCRIPTS / "step_cleanup.py")]
		self.assertEqual(subprocess.run([*command, "--version"], capture_output=True).returncode, 0)
		self.assertEqual(subprocess.run([*command, "does-not-exist.step"], capture_output=True).returncode, 2)

	def testBlindHolePreservesSmallPin(self) -> None:
		import cadquery as cq
		from modules.cad_geometry import HoleRemover, boreFaces, completeGroups

		block = cq.Workplane("XY").box(10, 10, 2).val()
		bore = cq.Solid.makeCylinder(0.25, 0.6, (2, 0, 0.4))
		pin = cq.Solid.makeCylinder(0.1, 1, (-2, 0, 1))
		original = block.cut(bore).fuse(pin)
		edited, count = HoleRemover(0.8).edit(original)
		self.assertEqual(count, 1)
		self.assertFalse(completeGroups(boreFaces(edited, 0.8)))
		self.assertAlmostEqual(edited.Volume() - original.Volume(), math.pi * 0.25 ** 2 * 0.6, places=7)
		self.assertAlmostEqual(edited.BoundingBox().zmax, 2.0, places=7)

	def testMixedAssemblyRefusal(self) -> None:
		import cadquery as cq

		with tempfile.TemporaryDirectory() as temporary:
			path = Path(temporary) / "mixed.step"
			assembly = cq.Assembly(name="Main")
			assembly.add(cq.Workplane("XY").box(1, 1, 1).val(), name="R_Selected")
			assembly.add(cq.Workplane("XY").box(2, 2, 2).val(), name="U_Retained")
			assembly.export(str(path))
			with self.assertRaisesRegex(ValueError, "Mixed parent assembly"):
				StepGraph(path).prune(("R_", "CC_"))

	def testBoardComponentsAndInPlaceIdempotence(self) -> None:
		import cadquery as cq
		from modules.cad_geometry import CadModel, boreFaces, completeGroups

		with tempfile.TemporaryDirectory() as temporary:
			work = Path(temporary)
			board = cq.Workplane("XY").box(20, 20, 1.6).faces(">Z").workplane()
			for point, diameter in [((-6, 0), 0.254), ((-3, 0), 0.762), ((0, 0), 0.8), ((3, 0), 1.2)]:
				board = board.pushPoints([point]).hole(diameter).faces(">Z").workplane(centerOption="CenterOfBoundBox")
			parts = [("Board1", "PCB", board.findSolid(), (0, 0, 0)),
				("R1", "R_0603", cq.Workplane("XY").box(1, 0.5, 0.5).val(), (-4, 2, 1.2)),
				("C1", "CC_0603", cq.Workplane("XY").box(1, 0.5, 0.5).val(), (4, 2, 1.2)),
				("U1", "U_Keep", cq.Workplane("XY").box(2, 2, 0.5).val(), (0, -3, 1.2))]
			combined = None
			for wrapper, name, shape, location in parts:
				path = work / f"{wrapper}.step"
				assembly = cq.Assembly(name=wrapper)
				assembly.add(shape, name=name, loc=cq.Location(location))
				assembly.export(str(path))
				graph = StepGraph(path)
				if combined is None:
					combined = graph
				else:
					next_id = max(combined.entities) + 1
					mapping = {entity_id: next_id + index for index, entity_id in enumerate(graph.entities)}
					combined.entities.update({mapping[entity_id]: remapReferences(value, mapping) for entity_id, value in graph.entities.items()})
			source = work / "fixture.step"
			combined.write(source)
			output = work / "cleaned.step"
			report = runCleanup(source, output, 0.8, ("R_", "CC_"), False)
			self.assertEqual(report["components"]["removed_instances"], {"R_": 1, "CC_": 1})
			self.assertEqual(report["hole_instances_filled"], 2)
			self.assertEqual(report["remaining_instances"], 2)
			self.assertLess(report["output_bytes"], report["input_bytes"])
			self.assertTrue(report["roundtrip_valid"])
			model = CadModel(output)
			self.assertEqual(set(model.parts), {"PCB", "U_Keep"})
			diameters = sorted(round(group[0]["diameter"], 6) for group in completeGroups(boreFaces(model.parts["PCB"])))
			self.assertEqual(diameters, [0.8, 1.2])
			# Repeating cleanup in place must not resurrect holes or components.
			repeated = runCleanup(output, output, 0.8, ("R_", "CC_"), True)
			self.assertEqual(repeated["hole_instances_filled"], 0)
			self.assertTrue(Path(repeated["backup"]).is_file())
			self.assertEqual(len(list(work.glob("cleaned.step.cleanup*.json"))), 2)


if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO, format="%(message)s")
	unittest.main()
