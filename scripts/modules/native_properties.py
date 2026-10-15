"""Explicitly calibrated Pulsonix 14 (schema 7308) embedded-part prefix reader."""

import re
import struct
from typing import Any

from .native_archive import NativeArchive
from .native_plan import ArchiveProfile, NativeEditPlan, PropertyChanges
from .native_storage import NativeStorage


class NativeProperties:
	@staticmethod
	def readNames(data: bytes, profile: ArchiveProfile) -> list[dict[str, Any]]:
		declarations = [item for item in NativeArchive.inventory(data)["class_declarations"]
			if item["name"] == "CAttributeNameArray" and item["schema"] == profile.archive_schema]
		if len(declarations) != 1:
			raise ValueError("Expected one calibrated CAttributeNameArray declaration")
		position = declarations[0]["end"] + 2
		names = []
		while NativeArchive.word(data, position):
			start = position
			if NativeArchive.word(data, position) != profile.name_class_tag:
				raise ValueError("Unsupported attribute-name record layout")
			name = NativeArchive.readCString(data, position + 14)
			default = NativeArchive.readCString(data, name["end"] + 12)
			position = default["end"] + 2
			if position > len(data):
				raise ValueError("Truncated attribute-name record")
			names.append({"object_id": profile.first_name_object_id + len(names), "offset": start,
				"name": name["value"], "name_string": name, "end": position})
		if len({item["name"] for item in names}) != len(names):
			raise ValueError("Duplicate global attribute names")
		if not names or names[-1]["object_id"] >= 0x8000:
			raise ValueError("Attribute-name calibration outside supported object-ID range")
		return names

	@staticmethod
	def readPart(data: bytes, offset: int, profile: ArchiveProfile) -> dict[str, Any]:
		if NativeArchive.word(data, offset) != profile.part_class_tag:
			raise ValueError("Unexpected CPart tag")
		array_tag = NativeArchive.word(data, offset + 29)
		owner_id = NativeArchive.word(data, offset + 31)
		if not 0x8000 <= array_tag < 0xffff or not 0 < owner_id < 0x8000:
			raise ValueError("Unsupported CPart attribute array")
		position = offset + 33
		attributes = []
		attribute_tag = NativeArchive.word(data, position)
		while NativeArchive.word(data, position):
			start = position
			if NativeArchive.word(data, position) != attribute_tag or not 0x8000 <= attribute_tag < 0xffff:
				raise ValueError("Unsupported CAttribute tag")
			if NativeArchive.word(data, position + 2) != owner_id:
				raise ValueError("Attribute owner differs from CPart owner")
			name_id = NativeArchive.word(data, position + 14)
			value = NativeArchive.readCString(data, position + 16)
			position = value["end"] + 2
			attributes.append({"record_offset": start, "name_id": name_id, "value_string": value, "end": position})
		name = NativeArchive.readCString(data, position + 12)
		library = NativeArchive.readCString(data, name["end"])
		return {"offset": offset, "object_id": owner_id, "name": name["value"], "name_string": name,
			"library_string": library, "attributes": attributes, "array_class_tag": array_tag,
			"attribute_class_tag": attribute_tag}

	@staticmethod
	def mapParts(source_bytes: bytes, profile: ArchiveProfile) -> dict[str, Any]:
		if NativeStorage.hashBytes(source_bytes) != profile.source_sha256:
			raise ValueError("Calibration profile belongs to another file; do not reuse it after a save")
		if len({(anchor.part, anchor.attribute) for anchor in profile.anchors}) < 2:
			raise ValueError("Calibration requires at least two distinct attribute anchors")
		data = NativeStorage.readBytes(source_bytes)[("Contents",)]
		names = NativeProperties.readNames(data, profile)
		name_map = {item["object_id"]: item["name"] for item in names}
		pattern = struct.pack("<HHH", profile.part_class_tag, profile.archive_schema, 0)
		parts = []
		for match in re.finditer(re.escape(pattern), data):
			try:
				part = NativeProperties.readPart(data, match.start(), profile)
				if not part["library_string"]["value"].lower().endswith(".pal"):
					continue
				for attribute in part["attributes"]:
					attribute["name"] = name_map[attribute["name_id"]]
				part["values"] = {item["name"]: item["value_string"]["value"] for item in part["attributes"]}
				if len(part["values"]) != len(part["attributes"]):
					raise ValueError("Duplicate part attributes")
				parts.append(part)
			except (ValueError, KeyError, UnicodeDecodeError):
				continue
		if len(parts) != profile.expected_part_count or len({item["name"] for item in parts}) != len(parts):
			raise ValueError("Embedded-part count/name coverage differs from calibration")
		if len({item["object_id"] for item in parts}) != len(parts):
			raise ValueError("Duplicate CPart owner IDs")
		part_map = {item["name"]: item for item in parts}
		for anchor in profile.anchors:
			if part_map.get(anchor.part, {}).get("values", {}).get(anchor.attribute) != anchor.expected:
				raise ValueError(f"Calibration anchor failed: {anchor.part} / {anchor.attribute}")
		return {"source_sha256": profile.source_sha256, "contents_sha256": NativeStorage.hashBytes(data),
			"profile": profile.model_dump(mode="json"), "names": names, "parts": parts,
			"scope": "Embedded CPart definitions; local instance overrides and geometry are not mapped"}

	@staticmethod
	def makePlan(source_bytes: bytes, profile: ArchiveProfile, changes: PropertyChanges) -> NativeEditPlan:
		mapping = NativeProperties.mapParts(source_bytes, profile)
		data = NativeStorage.readBytes(source_bytes)[("Contents",)]
		part_map = {item["name"]: item for item in mapping["parts"]}
		name_map = {item["object_id"]: item for item in mapping["names"]}
		edits = []
		seen = set()
		final_names = {item["object_id"]: item["name"] for item in mapping["parts"]}
		for change in changes.changes:
			part = part_map[change.part]
			key = (change.part, change.field, change.attribute)
			if key in seen:
				raise ValueError("Duplicate property change")
			seen.add(key)
			guard_spans = [(part["offset"], 6), (part["offset"] + 29, 4)]
			if change.field == "attribute":
				matches = [item for item in part["attributes"] if item["name"] == change.attribute]
				if len(matches) != 1:
					raise ValueError("Only existing explicit, uniquely named properties can be edited")
				attribute = matches[0]
				location = attribute["value_string"]
				name_string = name_map[attribute["name_id"]]["name_string"]
				guard_spans.extend([(attribute["record_offset"], 16),
					(name_string["offset"], name_string["end"] - name_string["offset"])])
			else:
				if change.attribute is not None:
					raise ValueError("Attribute key is only valid for an attribute change")
				location = part["name_string" if change.field == "part_name" else "library_string"]
				if change.field == "part_name":
					if not change.value:
						raise ValueError("Part name must not be empty")
					final_names[part["object_id"]] = change.value
				elif not change.value.lower().endswith(".pal"):
					raise ValueError("Source library link must name a .pal")
			if location["value"] != change.expected:
				raise ValueError(f"Expected property value differs: {key}")
			edits.append({"kind": "cstring", "offset": location["offset"],
				"expected_hex": data[location["offset"]:location["end"]].hex(),
				"replacement_hex": NativeArchive.encodeCString(change.value).hex(),
				"reason": f"{change.part}: {change.attribute or change.field}",
				"guards": [{"offset": start, "expected_hex": data[start:start + size].hex(),
					"reason": "Calibrated CPart/attribute owner and name context"} for start, size in guard_spans]})
		if len(set(final_names.values())) != len(final_names):
			raise ValueError("Renaming would create duplicate embedded part names; use a proven retarget recipe")
		return NativeEditPlan.model_validate({"format_version": 1, "source_sha256": profile.source_sha256,
			"contents_sha256": mapping["contents_sha256"], "profile": "Pulsonix 14 schema 7308 calibrated CPart prefix",
			"evidence": profile.evidence, "edits": edits})
