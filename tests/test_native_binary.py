"""Check archive boundaries, refusal behavior, CFB preservation and publication."""

import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from modules.native_archive import ByteEdit, NativeArchive
from modules.native_editor import NativeEditor
from modules.native_plan import NativeEditPlan
from modules.native_storage import NativeStorage


class ArchiveTests(unittest.TestCase):
	def testLengthBoundariesAndSurrogates(self) -> None:
		for value in ("", "abc", "x" * 254, "x" * 255, "x" * 65534, "x" * 65535, "\U0001f600" * 128):
			with self.subTest(length=len(value)):
				encoded = NativeArchive.encodeCString(value)
				actual = NativeArchive.readCString(encoded, 0)
				self.assertEqual(actual["value"], value)
				self.assertEqual(actual["end"], len(encoded))
				self.assertEqual(actual["units"], len(value.encode("utf-16le")) // 2)

	def testTruncatedStringsFail(self) -> None:
		for malformed in (b"", b"\xff\xfe\xff", b"\xff\xfe\xff\xff", b"\xff\xfe\xff\xff\xff\xff", b"\xff\xfe\xff\x02x"):
			with self.subTest(encoded=malformed), self.assertRaises(ValueError):
				NativeArchive.readCString(malformed, 0)

	def testVariableLengthSplicesAndReferenceShift(self) -> None:
		first = NativeArchive.encodeCString("old")
		second = NativeArchive.encodeCString("second")
		data = b"header" + first + b"opaque" + second + struct.pack("<H", 123)
		word_offset = len(data) - 2
		edits = [ByteEdit(6, first, NativeArchive.encodeCString("longer replacement"), "cstring", "value"),
			ByteEdit(word_offset, struct.pack("<H", 123), struct.pack("<H", 456), "word", "existing ID")]
		updated = NativeArchive.splice(data, edits)
		NativeArchive.verify(data, updated, edits)
		self.assertEqual(NativeArchive.word(updated, NativeArchive.shiftedOffset(word_offset, edits)), 456)
		self.assertIn(b"opaque" + second, updated)

	def testWrongBytesOverlapAndClassTagEditsFail(self) -> None:
		data = NativeArchive.encodeCString("source")
		good = ByteEdit(0, data, NativeArchive.encodeCString("new"), "cstring", "value")
		for edits in ([good, good], [ByteEdit(0, b"bad", b"x", "cstring", "wrong bytes")],
			[ByteEdit(0, b"\xff\xfe", b"\x00\x80", "word", "class tag")]):
			with self.subTest(edits=edits), self.assertRaises(ValueError):
				NativeArchive.splice(data, edits)

	def testOutOfPlanChangesFail(self) -> None:
		data = NativeArchive.encodeCString("a") + b"unchanged"
		edits = [ByteEdit(0, data[:6], NativeArchive.encodeCString("b"), "cstring", "value")]
		updated = NativeArchive.splice(data, edits)
		with self.assertRaises(ValueError):
			NativeArchive.verify(data, updated[:-1] + b"!", edits)


@unittest.skipUnless(sys.platform == "win32", "Windows structured storage requires pywin32")
class StorageTests(unittest.TestCase):
	def setUp(self) -> None:
		import pythoncom
		self.temporary = tempfile.TemporaryDirectory(prefix="pulsonix_native_tests_")
		self.addCleanup(self.temporary.cleanup)
		self.directory = Path(self.temporary.name)
		self.source = self.directory / "source.sch"
		self.candidate = self.directory / "candidate.sch"
		self.audit = self.directory / "audit.json"
		self.backup = self.directory / "backup.sch"
		self.value = NativeArchive.encodeCString("old")
		self.contents = b"opaque header" + self.value + b"protected topology"
		storage = pythoncom.StgCreateDocfile(str(self.source), 0x1012, 0)
		for name, data in (("Contents", self.contents), ("\x05File_Type", b"SCH")):
			stream = storage.CreateStream(name, 0x1012, 0, 0)
			stream.Write(data)
			stream.Commit(0)
			stream = None
		child = storage.CreateStorage("Nested", 0x1012, 0, 0)
		stream = child.CreateStream("Keep", 0x1012, 0, 0)
		stream.Write(b"nested metadata")
		stream.Commit(0)
		stream = None
		child.Commit(0)
		child = None
		storage.Commit(0)
		storage = None
		self.original = self.source.read_bytes()
		self.plan_data = {"format_version": 1, "source_sha256": NativeStorage.hashBytes(self.original),
			"contents_sha256": NativeStorage.hashBytes(self.contents), "profile": "Synthetic bounded CString",
			"evidence": "Known synthetic structure; no application format claim",
			"edits": [{"kind": "cstring", "offset": 13, "expected_hex": self.value.hex(),
				"replacement_hex": NativeArchive.encodeCString("a longer new value").hex(), "reason": "existing value",
				"guards": [{"offset": 0, "expected_hex": b"opaque header".hex(), "reason": "owner context"}]}],
			"protected_ranges": [{"start": 13 + len(self.value), "end": len(self.contents), "reason": "topology"}]}

	def testPrepareVerifyAndAtomicPublish(self) -> None:
		plan = NativeEditPlan.model_validate(self.plan_data)
		audit = NativeEditor.prepare(self.source, self.candidate, self.audit, plan)
		self.assertEqual(self.source.read_bytes(), self.original)
		self.assertEqual(audit.application_validation, "not_performed")
		NativeEditor.verify(self.source, self.candidate, audit)
		streams = NativeStorage.readFile(self.candidate)
		self.assertEqual(streams[("Nested", "Keep")], b"nested metadata")
		self.assertEqual(streams[("\x05File_Type",)], b"SCH")
		published = NativeEditor.publish(self.source, self.candidate, self.audit, self.backup)
		self.assertEqual(published.status, "published_offline_verified")
		self.assertEqual(self.backup.read_bytes(), self.original)
		self.assertEqual(self.source.read_bytes(), self.candidate.read_bytes())

	def testInPlacePublish(self) -> None:
		NativeEditor.prepare(self.source, self.candidate, self.audit, NativeEditPlan.model_validate(self.plan_data))
		NativeEditor.publish(self.source, self.candidate, self.audit, self.backup, in_place=True)
		self.assertEqual(self.backup.read_bytes(), self.original)
		self.assertEqual(self.source.read_bytes(), self.candidate.read_bytes())

	def testStaleSourceRefusedBeforeOutputs(self) -> None:
		plan = NativeEditPlan.model_validate(self.plan_data)
		self.source.write_bytes(self.original + b"changed")
		with self.assertRaises(ValueError):
			NativeEditor.prepare(self.source, self.candidate, self.audit, plan)
		self.assertFalse(self.candidate.exists())
		self.assertFalse(self.audit.exists())

	def testConcurrentSourceRefusedBeforeBackup(self) -> None:
		NativeEditor.prepare(self.source, self.candidate, self.audit, NativeEditPlan.model_validate(self.plan_data))
		changed = self.original + b"concurrent change"
		self.source.write_bytes(changed)
		with self.assertRaises(ValueError):
			NativeEditor.publish(self.source, self.candidate, self.audit, self.backup)
		self.assertFalse(self.backup.exists())
		self.assertEqual(self.source.read_bytes(), changed)

	def testTamperedCandidateRefusedBeforeBackup(self) -> None:
		NativeEditor.prepare(self.source, self.candidate, self.audit, NativeEditPlan.model_validate(self.plan_data))
		self.candidate.write_bytes(self.candidate.read_bytes() + b"tampered")
		with self.assertRaises(ValueError):
			NativeEditor.publish(self.source, self.candidate, self.audit, self.backup)
		self.assertFalse(self.backup.exists())
		self.assertEqual(self.source.read_bytes(), self.original)

	def testGuardAndProtectedRangeRefuseBeforeMutation(self) -> None:
		for corruption in ("guard", "protected"):
			plan_data = json.loads(json.dumps(self.plan_data))
			if corruption == "guard":
				plan_data["edits"][0]["guards"][0]["expected_hex"] = "00"
			else:
				plan_data["protected_ranges"][0]["start"] = 0
			with self.subTest(corruption=corruption), self.assertRaises(ValueError):
				NativeEditor.prepare(self.source, self.candidate, self.audit, NativeEditPlan.model_validate(plan_data))
			self.assertFalse(self.candidate.exists())
			self.assertEqual(self.source.read_bytes(), self.original)

	def testLibraryWriterRefused(self) -> None:
		with self.assertRaises(ValueError):
			NativeEditor.prepare(self.source, self.directory / "library.pal", self.audit,
				NativeEditPlan.model_validate(self.plan_data))
		self.assertFalse((self.directory / "library.pal").exists())

	def testOriginalCannotBeUsedAsOutput(self) -> None:
		with self.assertRaises(ValueError):
			NativeEditor.prepare(self.source, self.source, self.audit, NativeEditPlan.model_validate(self.plan_data))
		self.assertEqual(self.source.read_bytes(), self.original)

	def testBomJsonPlanAcceptedByCli(self) -> None:
		plan_path = self.directory / "plan.json"
		plan_path.write_text(json.dumps(self.plan_data), encoding="utf-8-sig")
		command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/edit_native_design.py"),
			"prepare", "--source", str(self.source), "--candidate", str(self.candidate),
			"--audit", str(self.audit), "--plan", str(plan_path)]
		result = subprocess.run(command, capture_output=True, text=True, check=False)
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertTrue(self.audit.exists())
		self.assertEqual(self.source.read_bytes(), self.original)

	def testFailedAtomicReplacementKeepsOriginalAndBackup(self) -> None:
		NativeEditor.prepare(self.source, self.candidate, self.audit, NativeEditPlan.model_validate(self.plan_data))
		with patch("modules.native_editor.os.replace", side_effect=PermissionError("simulated sharing violation")):
			with self.assertRaises(PermissionError):
				NativeEditor.publish(self.source, self.candidate, self.audit, self.backup)
		self.assertEqual(self.source.read_bytes(), self.original)
		self.assertEqual(self.backup.read_bytes(), self.original)
		self.assertEqual(json.loads(self.audit.read_text(encoding="utf-8"))["status"], "candidate_offline_verified")


if __name__ == "__main__":
	unittest.main()
