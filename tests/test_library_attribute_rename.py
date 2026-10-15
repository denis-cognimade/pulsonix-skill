"""Exercise name-only edits, collisions, idempotence and backed-up publication."""

import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from modules.library_attribute_archive import SpannedAttributeArchive, encodeString
from modules.library_attribute_rename import LibraryAttributeRenamer
from modules.native_storage import NativeStorage


class SyntheticAttributeArchive:
	"""Build test-only records; production code never serializes object graphs."""

	def __init__(self) -> None:
		self.next_id = 47
		self.classes: dict[str, int] = {}

	def objectHeader(self, class_name: str) -> tuple[bytes, int]:
		if class_name in self.classes:
			header = struct.pack("<H", self.classes[class_name] | 32768)
		else:
			self.classes[class_name] = self.next_id
			self.next_id += 1
			header = struct.pack("<HHH", 65535, 7308, len(class_name)) + class_name.encode("ascii")
		object_id = self.next_id
		self.next_id += 1
		return header, object_id

	def build(self, attributes: list[tuple[str, str]]) -> bytes:
		header, object_id = self.objectHeader("CAttributeArray")
		result = bytes(range(29)) + header + b"\x00\x00"
		name_ids = []
		for name, value in attributes:
			header, object_id = self.objectHeader("CAttribute")
			result += header + bytes(12)
			header, object_id = self.objectHeader("CAttributeName")
			name_ids.append(object_id)
			result += header + bytes(12) + encodeString(name)[1] + bytes(range(12)) + encodeString("")[1] + b"\x03\x00"
			result += encodeString(value)[1] + b"\x00\x00"
		result += b"\x00\x00"
		header, object_id = self.objectHeader("CAttributeNameArray")
		result += header + b"\x00\x00"
		result += b"".join(struct.pack("<H", name_id) for name_id in name_ids)
		return result + b"\x00\x00opaque suffix, preserved"


class RenameRecordTests(unittest.TestCase):
	def renamer(self) -> LibraryAttributeRenamer:
		return LibraryAttributeRenamer(Path("example.pal"), {"Mfg1": "Manufacturer_Name", "Mfg1 Code": "Manufacturer_Part_Number"}, Path("unused-output"))

	def testNamesOnlyAndVariableLengths(self) -> None:
		data = SyntheticAttributeArchive().build([("Mfg1", "Maker \U0001f600"), ("Mfg1 Code", "X-123"), ("Comment", "Mfg1")])
		updated, report = self.renamer().preparePart("Part-A", data)
		self.assertEqual(report["renamed_definitions"], 2)
		self.assertEqual(report["attributes"], {"Manufacturer_Name": "Maker \U0001f600", "Manufacturer_Part_Number": "X-123", "Comment": "Mfg1"})
		self.assertEqual(SpannedAttributeArchive(data).classes, SpannedAttributeArchive(updated).classes)
		self.assertTrue(updated.endswith(b"opaque suffix, preserved"))

	def testSameValueCollisionKeepsRecords(self) -> None:
		data = SyntheticAttributeArchive().build([("Mfg1", "Maker"), ("Manufacturer_Name", "Maker"), ("Mfg1 Code", "")])
		updated, report = self.renamer().preparePart("Part-A", data)
		self.assertEqual(report["identical_duplicates_after"], ["Manufacturer_Name"])
		self.assertEqual(len(SpannedAttributeArchive(data).objects), len(SpannedAttributeArchive(updated).objects))

	def testConflictingCollisionFails(self) -> None:
		data = SyntheticAttributeArchive().build([("Mfg1", "Maker"), ("Manufacturer_Name", "Other Maker")])
		with self.assertRaisesRegex(ValueError, "Conflicting destination"):
			self.renamer().preparePart("Part-A", data)

	def testRepeatDoesNotRebuildOrDeduplicate(self) -> None:
		data = SyntheticAttributeArchive().build([("Mfg1", "Maker"), ("Manufacturer_Name", "Maker"), ("Mfg1 Code", "X")])
		updated, first = self.renamer().preparePart("Part-A", data)
		repeated, second = self.renamer().preparePart("Part-A", updated)
		self.assertEqual(updated, repeated)
		self.assertEqual(second["renamed_definitions"], 0)
		self.assertEqual(first["attributes"], second["attributes"])

	def testUnsupportedLayoutAndMissingField(self) -> None:
		with self.assertRaises(ValueError):
			self.renamer().preparePart("Part-A", b"invalid")
		data = SyntheticAttributeArchive().build([("Value", "10k")])
		updated, report = self.renamer().preparePart("Part-A", data)
		self.assertEqual(updated, data)
		self.assertEqual(report["attributes"], {"Value": "10k"})


class RenamePublicationTests(unittest.TestCase):
	def setUp(self) -> None:
		if os.name != "nt":
			self.skipTest("Compound-storage writing uses Windows pywin32")
		import pythoncom
		self.temporary = tempfile.TemporaryDirectory(prefix="pulsonix_library_rename_test_")
		self.addCleanup(self.temporary.cleanup)
		self.directory = Path(self.temporary.name)
		self.library = self.directory / "source.pal"
		storage = pythoncom.StgCreateDocfile(str(self.library), 0x1012, 0)
		child = storage.CreateStorage("[1]", 0x1012, 0, 0)
		data = SyntheticAttributeArchive().build([("Mfg1", "Maker"), ("Mfg1 Code", "X")])
		for name, value in (("Part-A", data), ("[\x01Part Body]", b"opaque pin and gate records"), ("[\x01Part Info]", b"metadata")):
			stream = child.CreateStream(name, 0x1012, 0, 0)
			stream.Write(value)
			stream.Commit(0)
			stream = None
		child.Commit(0)
		child = None
		storage.Commit(0)
		storage = None
		self.index = b"1\tGroup\t#Pins\nPart-A\t[1]\t2\n"
		self.library.with_suffix(".palx").write_bytes(self.index)
		self.original = self.library.read_bytes()
		self.streams = NativeStorage.readFile(self.library)
		self.renames = {"Mfg1": "Manufacturer_Name", "Mfg1 Code": "Manufacturer_Part_Number"}

	def testPublishBacksUpAndPreservesOtherStreams(self) -> None:
		report = LibraryAttributeRenamer(self.library, self.renames, self.directory / "stage").execute(True)
		self.assertEqual(report["status"], "published_offline_verified")
		self.assertEqual((Path(report["backup"]) / self.library.name).read_bytes(), self.original)
		self.assertEqual(self.library.with_suffix(".palx").read_bytes(), self.index)
		actual = NativeStorage.readFile(self.library)
		for path, value in self.streams.items():
			if path != ("[1]", "Part-A"):
				self.assertEqual(actual[path], value)
		published = self.library.read_bytes()
		repeated = LibraryAttributeRenamer(self.library, self.renames, self.directory / "repeat").execute(True)
		self.assertEqual(repeated["status"], "already_renamed")
		self.assertEqual(self.library.read_bytes(), published)

	def testConcurrentSourceChangeBlocksPublication(self) -> None:
		calls = []
		def preflight(library_path: Path) -> None:
			calls.append(library_path)
			if len(calls) == 2:
				self.library.with_suffix(".palx").write_bytes(self.index + b"concurrent edit")
		with patch("modules.library_attribute_rename.NativeLibraryAccess.requireWritableLibrary", side_effect=preflight):
			with self.assertRaisesRegex(ValueError, "changed before publication"):
				LibraryAttributeRenamer(self.library, self.renames, self.directory / "stage").execute(True)
		self.assertEqual(self.library.read_bytes(), self.original)
		self.assertTrue(self.library.with_suffix(".palx").read_bytes().endswith(b"concurrent edit"))


if __name__ == "__main__":
	unittest.main()
