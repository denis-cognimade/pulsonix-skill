"""Verify read-only behavior without connecting to a live application."""

from pathlib import Path
import sys
import unittest
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from modules.part_snapshot import PartSnapshotReader


class FakeClient:
	def __init__(self, footprints: list[dict[str, str]] | None = None, attributes_only: bool = False) -> None:
		self.footprints = footprints or []
		self.attributes_only = attributes_only
		self.requested: list[tuple[int, str]] = []

	def call(self, method: str, *arguments: Any, object_id: int = 0) -> Any:
		if method == "Contains":
			return True
		if method == "Find":
			return 10
		raise AssertionError(f"Unexpected method {method}")

	def get(self, object_id: int, name: str) -> Any:
		self.requested.append((object_id, name))
		if object_id == 11:
			return {"Name": "Manufacturer", "Value": "Example"}[name]
		if name == "Name":
			return "ExamplePart"
		if name == "Attributes":
			return [11]
		if self.attributes_only:
			raise AssertionError(f"Properties-only read attempted structural property {name}")
		if name == "DefaultFootprintName":
			if not self.footprints:
				raise AssertionError("Missing-footprint part cannot return a default footprint")
			return "ExampleFootprint"
		return {
			"Gates": [], "Pins": [], "Description": "Example", "NameStem": "U",
			"PinCount": 0, "Footprints": self.footprints,
		}[name]


class PartSnapshotTests(unittest.TestCase):
	def testPartWithoutFootprintsDoesNotQueryDefault(self) -> None:
		client = FakeClient()
		result = PartSnapshotReader().readPartFromOpenLibrary(client, 1, "ExamplePart")
		self.assertEqual(result["footprints"], [])
		self.assertEqual(result["default_footprint"], "")
		self.assertNotIn((10, "DefaultFootprintName"), client.requested)

	def testAssignedFootprintIsStillRead(self) -> None:
		client = FakeClient([{"name": "ExampleFootprint"}])
		result = PartSnapshotReader().readPartFromOpenLibrary(client, 1, "ExamplePart")
		self.assertEqual(result["default_footprint"], "ExampleFootprint")

	def testAttributeReadAvoidsAllStructuralProperties(self) -> None:
		client = FakeClient(attributes_only=True)
		result = PartSnapshotReader().readAttributesFromOpenLibrary(client, 1, "ExamplePart")
		self.assertEqual(result, {"name": "ExamplePart", "attributes": {"Manufacturer": "Example"}})


if __name__ == "__main__":
	unittest.main()
