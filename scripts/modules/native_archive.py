"""Bounded MFC CString codecs and typed splices, not a complete archive serializer."""

from dataclasses import dataclass
import re
import struct
from typing import Any


@dataclass(frozen=True)
class ByteEdit:
	offset: int
	expected: bytes
	replacement: bytes
	kind: str
	reason: str

	@property
	def end(self) -> int:
		return self.offset + len(self.expected)


class NativeArchive:
	@staticmethod
	def word(data: bytes, offset: int) -> int:
		if offset < 0 or offset + 2 > len(data):
			raise ValueError(f"WORD outside stream at {offset}")
		return struct.unpack_from("<H", data, offset)[0]

	@staticmethod
	def readCString(data: bytes, offset: int) -> dict[str, Any]:
		if offset < 0 or data[offset:offset + 3] != b"\xff\xfe\xff":
			raise ValueError(f"No Unicode CString at {offset}")
		position = offset + 3
		if position >= len(data):
			raise ValueError("Missing CString length")
		units = data[position]
		position += 1
		if units == 255:
			units = NativeArchive.word(data, position)
			position += 2
			if units == 65535:
				if position + 4 > len(data):
					raise ValueError("Missing extended CString length")
				units = struct.unpack_from("<I", data, position)[0]
				position += 4
		end = position + units * 2
		if end > len(data):
			raise ValueError("CString exceeds stream")
		return {"offset": offset, "payload_offset": position, "end": end, "units": units,
			"value": data[position:end].decode("utf-16le")}

	@staticmethod
	def encodeCString(value: str) -> bytes:
		payload = value.encode("utf-16le")
		units = len(payload) // 2
		if units < 255:
			length = bytes([units])
		elif units < 65535:
			length = b"\xff" + struct.pack("<H", units)
		else:
			length = b"\xff\xff\xff" + struct.pack("<I", units)
		return b"\xff\xfe\xff" + length + payload

	@staticmethod
	def inventory(data: bytes) -> dict[str, Any]:
		strings = []
		for match in re.finditer(b"\xff\xfe\xff", data):
			try:
				strings.append(NativeArchive.readCString(data, match.start()))
			except (ValueError, UnicodeDecodeError):
				continue
		classes = []
		for match in re.finditer(b"\xff\xff", data):
			offset = match.start()
			if offset + 6 > len(data):
				continue
			schema, length = struct.unpack_from("<HH", data, offset + 2)
			name_bytes = data[offset + 6:offset + 6 + length]
			if 2 <= length <= 128 and len(name_bytes) == length and re.fullmatch(rb"C[A-Za-z][A-Za-z0-9_]*", name_bytes):
				classes.append({"offset": offset, "end": offset + 6 + length,
					"schema": schema, "name": name_bytes.decode("ascii")})
		return {"strings": strings, "class_declarations": classes,
			"interpretation": "Signature candidates only; does not recover archive allocation IDs"}

	@staticmethod
	def orderedEdits(data: bytes, edits: list[ByteEdit]) -> list[ByteEdit]:
		ordered = sorted(edits, key=lambda edit: edit.offset)
		previous_end = -1
		for edit in ordered:
			if edit.offset < 0 or edit.end > len(data) or not edit.expected or edit.offset < previous_end:
				raise ValueError("Overlapping, empty or out-of-bounds edit")
			if data[edit.offset:edit.end] != edit.expected:
				raise ValueError(f"Expected bytes differ at {edit.offset}: {edit.reason}")
			if edit.kind == "cstring":
				old = NativeArchive.readCString(data, edit.offset)
				new = NativeArchive.readCString(edit.replacement, 0)
				if old["end"] != edit.end or new["end"] != len(edit.replacement):
					raise ValueError("CString edit must replace exactly one complete string")
			elif edit.kind == "word":
				if len(edit.expected) != 2 or len(edit.replacement) != 2:
					raise ValueError("WORD edits must preserve their two-byte width")
				if max(NativeArchive.word(edit.expected, 0), NativeArchive.word(edit.replacement, 0)) >= 0x8000:
					raise ValueError("WORD editing is restricted to ordinary object references or zero")
			else:
				raise ValueError(f"Unsupported edit type: {edit.kind}")
			previous_end = edit.end
		return ordered

	@staticmethod
	def shiftedOffset(offset: int, edits: list[ByteEdit]) -> int:
		return offset + sum(len(edit.replacement) - len(edit.expected) for edit in edits if edit.end <= offset)

	@staticmethod
	def splice(data: bytes, edits: list[ByteEdit]) -> bytes:
		ordered = NativeArchive.orderedEdits(data, edits)
		segments = []
		position = 0
		for edit in ordered:
			segments.extend([data[position:edit.offset], edit.replacement])
			position = edit.end
		segments.append(data[position:])
		return b"".join(segments)

	@staticmethod
	def verify(data: bytes, updated: bytes, edits: list[ByteEdit]) -> None:
		ordered = NativeArchive.orderedEdits(data, edits)
		if NativeArchive.splice(data, ordered) != updated:
			raise ValueError("Candidate differs outside planned edits")
		for edit in ordered:
			offset = NativeArchive.shiftedOffset(edit.offset, ordered)
			if updated[offset:offset + len(edit.replacement)] != edit.replacement:
				raise ValueError("Shifted edit readback failed")
			if edit.kind == "cstring":
				NativeArchive.readCString(updated, offset)
		for declaration in NativeArchive.inventory(data)["class_declarations"]:
			start, end = declaration["offset"], declaration["end"]
			if any(edit.offset < end and edit.end > start for edit in ordered):
				raise ValueError("Edits must not touch runtime-class declarations")
			shifted = NativeArchive.shiftedOffset(start, ordered)
			if updated[shifted:shifted + end - start] != data[start:end]:
				raise ValueError("Runtime-class declaration changed")
