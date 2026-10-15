"""Read and preserve the MFC attribute archives in the local part library."""

from dataclasses import dataclass, field
import struct
from typing import Any


@dataclass(eq=False)
class ArchiveObject:
	class_name: str
	schema: int
	fields: dict[str, Any] = field(default_factory=dict)


class AttributeArchive:
	def __init__(self, data: bytes) -> None:
		self.data = data
		self.position = 0
		self.next_id = 47
		self.classes: dict[int, tuple[str, int]] = {}
		self.objects: dict[int, ArchiveObject] = {}
		self.prefix = self.take(29)
		self.attributes = self.readObject()
		self.names = self.readObject()
		self.suffix = data[self.position:]
		if self.attributes is None or self.attributes.class_name != "CAttributeArray":
			raise ValueError("Invalid attribute array")
		if self.names is None or self.names.class_name != "CAttributeNameArray":
			raise ValueError("Invalid attribute-name array")

	def take(self, count: int) -> bytes:
		if count < 0 or self.position + count > len(self.data):
			raise ValueError(f"Archive truncated at {self.position}")
		result = self.data[self.position:self.position + count]
		self.position += count
		return result

	def word(self) -> int:
		return struct.unpack("<H", self.take(2))[0]

	def readString(self) -> tuple[str, bytes]:
		start = self.position
		if self.take(3) != b"\xff\xfe\xff":
			raise ValueError(f"Expected Unicode CString at {start}")
		length = self.take(1)[0]
		if length == 255:
			length = self.word()
			if length == 65535:
				length = struct.unpack("<I", self.take(4))[0]
		value = self.take(length * 2).decode("utf-16le")
		return value, self.data[start:self.position]

	def readObject(self) -> ArchiveObject | None:
		tag = self.word()
		if tag == 0:
			return None
		if tag == 65535:
			schema = self.word()
			if schema != 7308:
				raise ValueError(f"Unsupported native library attribute schema {schema}; expected observed schema 7308")
			class_name = self.take(self.word()).decode("ascii")
			self.classes[self.next_id] = (class_name, schema)
			self.next_id += 1
		elif tag & 32768:
			if tag & 32767 not in self.classes:
				raise ValueError(f"Unknown archive class reference {tag & 32767}")
			class_name, schema = self.classes[tag & 32767]
		else:
			if tag not in self.objects:
				raise ValueError(f"Unknown archive object reference {tag}")
			return self.objects[tag]
		result = ArchiveObject(class_name, schema)
		self.objects[self.next_id] = result
		self.next_id += 1
		fields = result.fields
		if class_name in ("CAttributeArray", "CAttributeNameArray"):
			fields["header"] = self.take(2)
			items = []
			while (item := self.readObject()) is not None:
				items.append(item)
			fields["items"] = items
		elif class_name == "CAttribute":
			fields["header"] = self.take(12)
			fields["name"] = self.readObject()
			fields["value"] = self.readString()
			fields["tail"] = self.take(2)
		elif class_name == "CAttributeName":
			fields["header"] = self.take(12)
			fields["name"] = self.readString()
			fields["metadata"] = self.take(12)
			fields["default"] = self.readString()
			fields["tail"] = self.take(2)
		else:
			raise ValueError(f"Unsupported archive class {class_name}")
		return result

	def values(self) -> dict[str, str]:
		result = {}
		for attribute in self.attributes.fields["items"]:
			name = attribute.fields["name"].fields["name"][0]
			if name in result:
				raise ValueError(f"Duplicate attribute {name}")
			result[name] = attribute.fields["value"][0]
		return result

	def defaults(self) -> dict[str, str]:
		return {name.fields["name"][0]: name.fields["default"][0] for name in self.names.fields["items"]}

	def effectiveValues(self) -> dict[str, str]:
		return {**self.defaults(), **self.values()}



def encodeString(value: str) -> tuple[str, bytes]:
	encoded = value.encode("utf-16le")
	length = len(encoded) // 2
	if length < 255:
		prefix = bytes([length])
	elif length < 65535:
		prefix = b"\xff" + struct.pack("<H", length)
	else:
		prefix = b"\xff\xff\xff" + struct.pack("<I", length)
	return value, b"\xff\xfe\xff" + prefix + encoded


class SpannedAttributeArchive(AttributeArchive):
	def __init__(self, data: bytes) -> None:
		self.string_spans: dict[int, tuple[int, int]] = {}
		super().__init__(data)

	def readString(self) -> tuple[str, bytes]:
		start = self.position
		result = super().readString()
		self.string_spans[id(result)] = (start, self.position)
		return result

	def nameSpan(self, object_id: int) -> tuple[int, int]:
		return self.string_spans[id(self.objects[object_id].fields["name"])]

	def graph(self) -> dict[str, Any]:
		object_ids = {id(value): object_id for object_id, value in self.objects.items()}

		def normalize(value: Any) -> Any:
			if isinstance(value, ArchiveObject):
				return {"reference": object_ids[id(value)]}
			if isinstance(value, dict):
				return {key: normalize(item) for key, item in value.items()}
			if isinstance(value, (list, tuple)):
				return [normalize(item) for item in value]
			return value

		return {
			"classes": self.classes,
			"next_id": self.next_id,
			"prefix": self.prefix,
			"suffix": self.suffix,
			"objects": {object_id: {"class": value.class_name, "schema": value.schema, "fields": normalize(value.fields)} for object_id, value in self.objects.items()},
		}

	def logicalValues(self) -> tuple[dict[str, str], list[str]]:
		values: dict[str, str] = {}
		identical_duplicates = []
		for attribute in self.attributes.fields["items"]:
			name = attribute.fields["name"].fields["name"][0]
			value = attribute.fields["value"][0]
			if name in values:
				if values[name] != value:
					raise ValueError(f"Conflicting values for existing destination attribute {name}")
				identical_duplicates.append(name)
			values[name] = value
		return values, identical_duplicates
