"""Read Pulsonix part data directly through the local scripting pipe."""

from pathlib import Path
from typing import Any

from modules.pipe_client import PulsonixPipeClient, PulsonixPipeError


class PartSnapshotReader:
	"""Build plain dictionaries from Pulsonix part-library object handles."""

	_instance: "PartSnapshotReader | None" = None

	@classmethod
	def getInstance(cls) -> "PartSnapshotReader":
		if cls._instance is None:
			cls._instance = cls()
		return cls._instance

	def readPart(self, library_path: Path, part_name: str) -> dict[str, Any]:
		client = PulsonixPipeClient.getInstance()
		library_id: int | None = None
		try:
			client.connect()
			version = self._requireString(client.call("GetVersion"), "GetVersion")
			library_id = self._requireId(
				client.call("OpenPartLibrary", str(library_path.resolve()), True),
				"OpenPartLibrary",
			)
			part = self.readPartFromOpenLibrary(client, library_id, part_name)
			return {
				"pulsonix_version": version,
				"library": str(library_path.resolve()),
				"part": part,
			}
		finally:
			if library_id is not None:
				try:
					client.call("Delete", library_id)
				except Exception:
					pass
			client.close()

	def readPartFromOpenLibrary(
		self,
		client: PulsonixPipeClient,
		library_id: int,
		part_name: str,
	) -> dict[str, Any]:
		contains_part = client.call("Contains", part_name, object_id=library_id)
		if contains_part is not True:
			raise KeyError(f"Part {part_name} is not in the open Pulsonix library")
		part_id = self._requireId(
			client.call("Find", part_name, object_id=library_id),
			"PartLibrary.Find",
		)
		attribute_ids = self._requireIdList(client.get(part_id, "Attributes"), "Attributes")
		gate_ids = self._requireIdList(client.get(part_id, "Gates"), "Gates")
		ungated_pin_ids = self._requireIdList(client.get(part_id, "Pins"), "Pins")
		footprints = self._requireList(client.get(part_id, "Footprints"), "Part.Footprints")
		return {
			"name": self._requireString(client.get(part_id, "Name"), "Part.Name"),
			"description": self._requireString(
				client.get(part_id, "Description"),
				"Part.Description",
			),
			"name_stem": self._requireString(
				client.get(part_id, "NameStem"),
				"Part.NameStem",
			),
			"pin_count": self._requireInteger(
				client.get(part_id, "PinCount"),
				"Part.PinCount",
			),
			"default_footprint": self._requireString(
				client.get(part_id, "DefaultFootprintName"),
				"Part.DefaultFootprintName",
			) if footprints else "",
			"footprints": footprints,
			"attributes": {
				self._requireString(client.get(attribute_id, "Name"), "Attribute.Name"):
				self._requireString(client.get(attribute_id, "Value"), "Attribute.Value")
				for attribute_id in attribute_ids
			},
			"ungated_pins": [self._readPin(client, pin_id) for pin_id in ungated_pin_ids],
			"gates": [self._readGate(client, gate_id) for gate_id in gate_ids],
		}

	def readAttributesFromOpenLibrary(
		self,
		client: PulsonixPipeClient,
		library_id: int,
		part_name: str,
	) -> dict[str, Any]:
		"""Read only identity and attributes, without traversing part structure."""
		if client.call("Contains", part_name, object_id=library_id) is not True:
			raise KeyError(f"Part {part_name} is not in the open Pulsonix library")
		part_id = self._requireId(client.call("Find", part_name, object_id=library_id), "PartLibrary.Find")
		attribute_ids = self._requireIdList(client.get(part_id, "Attributes"), "Attributes")
		return {
			"name": self._requireString(client.get(part_id, "Name"), "Part.Name"),
			"attributes": {
				self._requireString(client.get(attribute_id, "Name"), "Attribute.Name"):
				self._requireString(client.get(attribute_id, "Value"), "Attribute.Value")
				for attribute_id in attribute_ids
			},
		}

	def _readGate(
		self,
		client: PulsonixPipeClient,
		gate_id: int,
	) -> dict[str, Any]:
		pin_ids = self._requireIdList(client.get(gate_id, "Pins"), "Gate.Pins")
		return {
			"name": self._requireString(client.get(gate_id, "Name"), "Gate.Name"),
			"default_symbol": self._requireString(
				client.get(gate_id, "DefaultSymbolName"),
				"Gate.DefaultSymbolName",
			),
			"symbols": self._requireList(client.get(gate_id, "Symbols"), "Gate.Symbols"),
			"swap_group": self._requireInteger(
				client.get(gate_id, "SwapGroup"),
				"Gate.SwapGroup",
			),
			"pins": [self._readPin(client, pin_id) for pin_id in pin_ids],
		}

	def _readPin(
		self,
		client: PulsonixPipeClient,
		pin_id: int,
	) -> dict[str, Any]:
		return {
			"name": self._requireString(client.get(pin_id, "Name"), "PartPin.Name"),
			"logic_name": self._requireString(
				client.get(pin_id, "LogicName"),
				"PartPin.LogicName",
			),
			"pcb_pin": self._requireString(
				client.get(pin_id, "PcbPinName"),
				"PartPin.PcbPinName",
			),
			"scm_pin": self._requireString(
				client.get(pin_id, "ScmPinName"),
				"PartPin.ScmPinName",
			),
			"signal_name": self._requireString(
				client.get(pin_id, "SignalName"),
				"PartPin.SignalName",
			),
			"swap_group": self._requireInteger(
				client.get(pin_id, "SwapGroup"),
				"PartPin.SwapGroup",
			),
		}

	def _requireId(self, value: Any, operation_name: str) -> int:
		if isinstance(value, bool) or not isinstance(value, int):
			raise PulsonixPipeError(
				f"{operation_name} returned {type(value).__name__}, expected object ID"
			)
		return value

	def _requireIdList(self, value: Any, operation_name: str) -> list[int]:
		items = self._requireList(value, operation_name)
		if any(isinstance(item, bool) or not isinstance(item, int) for item in items):
			raise PulsonixPipeError(f"{operation_name} returned an invalid object-ID list")
		return items

	def _requireList(self, value: Any, operation_name: str) -> list[Any]:
		if not isinstance(value, list):
			raise PulsonixPipeError(
				f"{operation_name} returned {type(value).__name__}, expected list"
			)
		return value

	def _requireString(self, value: Any, operation_name: str) -> str:
		if not isinstance(value, str):
			raise PulsonixPipeError(
				f"{operation_name} returned {type(value).__name__}, expected string"
			)
		return value

	def _requireInteger(self, value: Any, operation_name: str) -> int:
		if isinstance(value, bool) or not isinstance(value, int):
			raise PulsonixPipeError(
				f"{operation_name} returned {type(value).__name__}, expected integer"
			)
		return value
