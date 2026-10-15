"""Rename existing native .pal CStrings without rebuilding archive records."""

import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from modules.library_access import NativeLibraryAccess
from modules.library_attribute_archive import SpannedAttributeArchive, encodeString
from modules.native_storage import NativeStorage


class LibraryAttributeRenamer:
	def __init__(self, library: Path, renames: dict[str, str], output: Path) -> None:
		self.library = library.resolve()
		self.output = output.resolve()
		self.renames = renames
		if self.library.suffix.lower() != ".pal":
			raise ValueError("Existing-name renaming supports .pal part libraries only")
		if not renames or any(not source or not target or any(character in source + target for character in "\x00\r\n") for source, target in renames.items()):
			raise ValueError("Provide nonempty old=new attribute names without control characters")
		if len(set(renames.values())) != len(renames):
			raise ValueError("Multiple source names cannot share a destination in one operation")
		if any(target in renames and source != target for source, target in renames.items()):
			raise ValueError("Chained or cyclic renames are unsupported; use independent name pairs")

	def fileHashes(self, directory: Path) -> dict[str, str]:
		return {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
			for name in (self.library.name, self.library.with_suffix(".palx").name)}

	def saveJson(self, filename: str, value: Any) -> None:
		(self.output / filename).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")

	def replaceSpans(self, data: bytes, replacements: list[tuple[int, int, bytes]]) -> bytes:
		result = data
		previous_start = len(data)
		for start, end, replacement in sorted(replacements, reverse=True):
			if not 0 <= start < end <= previous_start:
				raise ValueError("Overlapping or invalid CString edit")
			result = result[:start] + replacement + result[end:]
			previous_start = start
		return result

	def preparePart(self, name: str, data: bytes) -> tuple[bytes, dict[str, Any]]:
		before = SpannedAttributeArchive(data)
		original_values, duplicates_before = before.logicalValues()
		expected_values = dict(original_values)
		for source, target in self.renames.items():
			if source not in original_values or source == target:
				continue
			if target in original_values and original_values[target] != original_values[source]:
				raise ValueError(f"Conflicting destination values on {name}: {source} -> {target}")
			expected_values[target] = expected_values.pop(source)
		replacements = []
		renamed_ids: dict[int, str] = {}
		expected_graph = before.graph()
		for object_id, value in before.objects.items():
			if value.class_name != "CAttributeName":
				continue
			source = value.fields["name"][0]
			if source in self.renames and source != self.renames[source]:
				start, end = before.nameSpan(object_id)
				target, encoded = encodeString(self.renames[source])
				replacements.append((start, end, encoded))
				renamed_ids[object_id] = source
				expected_graph["objects"][object_id]["fields"]["name"] = [target, encoded]
		updated = self.replaceSpans(data, replacements)
		after = SpannedAttributeArchive(updated)
		if after.graph() != expected_graph:
			raise ValueError(f"Object IDs, references, values or metadata changed on {name}")
		actual_values, duplicates_after = after.logicalValues()
		if actual_values != expected_values:
			raise ValueError(f"Attribute rename mismatch on {name}")
		reverse_edits = []
		for object_id, source in renamed_ids.items():
			start, end = after.nameSpan(object_id)
			reverse_edits.append((start, end, encodeString(source)[1]))
		if self.replaceSpans(updated, reverse_edits) != data:
			raise ValueError(f"Reversing name edits failed to restore every original byte on {name}")
		return updated, {
			"name": name,
			"attributes": actual_values,
			"renamed_definitions": len(renamed_ids),
			"identical_duplicates_before": duplicates_before,
			"identical_duplicates_after": duplicates_after,
			"missing_source_names": [source for source in self.renames if source not in original_values],
		}

	def writePrepared(self, path: Path, replacements: dict[tuple[str, ...], bytes]) -> None:
		import pythoncom
		storage = pythoncom.StgOpenStorage(str(path), None, 18, None, 0)
		try:
			for (group, name), data in replacements.items():
				child = storage.OpenStorage(group, None, 18, None, 0)
				stream = None
				try:
					stream = child.OpenStream(name, None, 18, 0)
					stream.Seek(0, 0)
					if stream.Write(data) != len(data):
						raise OSError(f"Incomplete stream write on {name}")
					stream.SetSize(len(data))
					stream.Commit(0)
					stream = None
					child.Commit(0)
				finally:
					stream = None
					child = None
			storage.Commit(0)
		finally:
			storage = None

	def execute(self, publish: bool = False) -> dict[str, Any]:
		if self.output.exists():
			raise FileExistsError(f"Choose a new output directory: {self.output}")
		if publish:
			NativeLibraryAccess.getInstance().requireWritableLibrary(self.library)
		baseline = self.fileHashes(self.library.parent)
		original_streams = NativeStorage.readFile(self.library)
		with self.library.with_suffix(".palx").open(encoding="utf-8-sig", newline="") as source:
			reader = csv.DictReader(source, delimiter="\t")
			rows = list(reader)
			if not reader.fieldnames or "1" not in reader.fieldnames or "Group" not in reader.fieldnames:
				raise ValueError("Unsupported part index header")
			if any(source in reader.fieldnames or f"<{source}>" in reader.fieldnames for source in self.renames):
				raise ValueError("Requested name is an indexed column; this helper does not regenerate indexes")
		paths = [(row["Group"], row["1"]) for row in rows]
		if not paths or len(paths) != len(set(paths)) or len({path[1] for path in paths}) != len(paths):
			raise ValueError("Empty or duplicate part index entries")
		replacements = {}
		parts = []
		for path in paths:
			updated, report = self.preparePart(path[1], original_streams[path])
			if updated != original_streams[path]:
				replacements[path] = updated
			parts.append(report)
		report = {
			"status": "prepared_offline_verified",
			"library": str(self.library),
			"original_hashes": baseline,
			"part_count": len(parts),
			"changed_parts": len(replacements),
			"renamed_definitions": sum(part["renamed_definitions"] for part in parts),
			"unchanged_other_streams": len(original_streams) - len(replacements),
			"parts_with_identical_duplicates": sum(bool(part["identical_duplicates_after"]) for part in parts),
			"renames": self.renames,
			"application_tested": False,
			"parts": parts,
		}
		self.output.mkdir(parents=True)
		if not replacements:
			if self.fileHashes(self.library.parent) != baseline:
				raise ValueError("Source changed during inspection")
			report["status"] = "already_renamed" if all(all(target in part["attributes"] for target in self.renames.values()) for part in parts) else "no_matching_attributes"
			self.saveJson("result.json", report)
			return report
		for name in baseline:
			shutil.copy2(self.library.parent / name, self.output / name)
		if self.fileHashes(self.output) != baseline or self.fileHashes(self.library.parent) != baseline:
			raise ValueError("Source changed while copying")
		prepared = self.output / self.library.name
		self.writePrepared(prepared, replacements)
		expected_streams = {**original_streams, **replacements}
		if NativeStorage.readFile(prepared) != expected_streams:
			raise ValueError("Prepared library differs from the exact planned stream edits")
		verified_hashes = self.fileHashes(self.output)
		if verified_hashes[self.library.with_suffix(".palx").name] != baseline[self.library.with_suffix(".palx").name]:
			raise ValueError("Part index changed")
		report["verified_hashes"] = verified_hashes
		self.saveJson("prepared.json", report)
		if not publish:
			return report
		NativeLibraryAccess.getInstance().requireWritableLibrary(self.library)
		if self.fileHashes(self.library.parent) != baseline or self.fileHashes(self.output) != verified_hashes:
			raise ValueError("Source or prepared files changed before publication")
		backup = self.library.parent / f"backup_before_attribute_rename_{datetime.now():%Y%m%d-%H%M%S-%f}"
		backup.mkdir()
		for name in baseline:
			shutil.copy2(self.library.parent / name, backup / name)
		if self.fileHashes(backup) != baseline or self.fileHashes(self.library.parent) != baseline:
			raise ValueError("Backup verification failed or source changed")
		self.saveJson("publication_started.json", {"backup": str(backup), "original_hashes": baseline})
		shutil.copy2(prepared, self.library)
		if self.fileHashes(self.library.parent) != verified_hashes or NativeStorage.readFile(self.library) != expected_streams:
			raise ValueError(f"Published library differs from the verified copy; inspect backup: {backup}")
		report.update({"status": "published_offline_verified", "backup": str(backup), "published_hashes": self.fileHashes(self.library.parent)})
		self.saveJson("result.json", report)
		return report
