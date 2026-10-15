"""Generate component-only PLX variants from a reference or explicit structure."""

import argparse
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys
from typing import Any

from modules.part_snapshot import PartSnapshotReader
from modules.runtime import RuntimeSupport


INVALID_FILENAME_PATTERN = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
POWER_MILLIWATT_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*mW\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ReferencePin:
	"""One gate pin copied from the verified Pulsonix reference part."""

	name: str
	logic_name: str
	pcb_pin: str
	scm_pin: str


@dataclass(frozen=True)
class ReferenceStructure:
	"""Supported single-gate structure used to generate related parts."""

	part_name: str
	part_number: str
	name_stem: str
	footprint: str
	symbol: str
	pins: tuple[ReferencePin, ...]


class VariantPlxGenerator:
	"""Generate reviewable PLX files without any Advanced API operation."""

	_instance: "VariantPlxGenerator | None" = None

	def __init__(self) -> None:
		self.runtime = RuntimeSupport.getInstance()
		self.logger = self.runtime.configureLogging("pulsonix.generate_variant_plx")
		self.reader = PartSnapshotReader.getInstance()

	@classmethod
	def getInstance(cls) -> "VariantPlxGenerator":
		if cls._instance is None:
			cls._instance = cls()
		return cls._instance

	def run(self, arguments: argparse.Namespace) -> int:
		try:
			parts_csv_path = Path(arguments.parts_csv)
			if not parts_csv_path.is_file():
				raise FileNotFoundError(
					f"PLX generation failed because CSV {parts_csv_path} does not exist"
				)

			if arguments.reference:
				if not arguments.library:
					raise ValueError("--library is required when --reference is used")
				library_path = Path(arguments.library)
				if not library_path.is_file():
					raise FileNotFoundError(
					f"PLX generation failed because library {library_path} does not exist"
				)
				reference = self._readReference(library_path, arguments.reference)
				if arguments.name_stem:
					reference = self._withNameStem(reference, arguments.name_stem)
			else:
				reference = self._explicitStructure(arguments)
			rows = self._readRows(parts_csv_path)
			output_directory = Path(arguments.output).resolve()
			output_directory.mkdir(parents=True, exist_ok=True)
			created_paths = self._generateFiles(
				reference,
				rows,
				output_directory,
				arguments.include_reference,
			)
			self.logger.info(
				f"Generated {len(created_paths)} component PLX files in {output_directory}"
			)
			for created_path in created_paths:
				self.logger.info(f"Generated {created_path.name}")
			return 0
		except Exception as error:
			self.logger.error(f"PLX generation failed because {error}")
			return 1

	def _readReference(
		self,
		library_path: Path,
		part_name: str,
	) -> ReferenceStructure:
		snapshot = self.reader.readPart(library_path, part_name)
		part = snapshot["part"]
		gates = part["gates"]
		if len(gates) != 1:
			raise ValueError(
				f"Reference part {part_name} has {len(gates)} gates; "
				"the component-only generator supports exactly one gate"
			)
		if part["ungated_pins"]:
			raise ValueError(
				f"Reference part {part_name} has ungated pins; generate its PLX manually"
			)
		gate = gates[0]
		if len(part["footprints"]) != 1:
			raise ValueError(
				f"Reference part {part_name} has {len(part['footprints'])} footprints; "
				"the component-only generator supports exactly one footprint"
			)
		if len(gate["symbols"]) != 1:
			raise ValueError(
				f"Reference part {part_name} has {len(gate['symbols'])} symbols; "
				"the component-only generator supports exactly one symbol"
			)
		if gate["swap_group"] != 0:
			raise ValueError(
				f"Reference part {part_name} uses gate swapping; generate its PLX manually"
			)
		pins = tuple(self._readReferencePin(pin) for pin in gate["pins"])
		if not pins or len(pins) != part["pin_count"]:
			raise ValueError(f"Reference part {part_name} has an unsupported pin layout")
		if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", part["name_stem"]):
			raise ValueError(
				f"Reference part {part_name} has unsupported name stem {part['name_stem']}"
			)
		return ReferenceStructure(
			part_name=part["name"],
			part_number=part["attributes"].get("Part Number", ""),
			name_stem=part["name_stem"],
			footprint=part["default_footprint"],
			symbol=gate["default_symbol"],
			pins=pins,
		)

	def _readReferencePin(self, pin: dict[str, Any]) -> ReferencePin:
		if pin["swap_group"] != 0:
			raise ValueError(f"Reference pin {pin['name']} uses pin swapping")
		if not pin["name"] or not pin["pcb_pin"] or not pin["scm_pin"]:
			raise ValueError(
				f"Reference pin {pin['name']} has an incomplete pin mapping"
			)
		return ReferencePin(
			name=pin["name"],
			logic_name=pin["logic_name"],
			pcb_pin=pin["pcb_pin"],
			scm_pin=pin["scm_pin"],
		)

	def _explicitStructure(self, arguments: argparse.Namespace) -> ReferenceStructure:
		missing_arguments = [
			argument_name
			for argument_name, argument_value in (
				("--symbol", arguments.symbol),
				("--footprint", arguments.footprint),
				("--name-stem", arguments.name_stem),
				("--pins", arguments.pins),
			)
			if not argument_value
		]
		if missing_arguments:
			raise ValueError(
				"Explicit structure mode requires " + ", ".join(missing_arguments)
			)
		if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", arguments.name_stem):
			raise ValueError(f"Unsupported name stem {arguments.name_stem}")
		pin_names = [pin_name.strip() for pin_name in arguments.pins.split(",")]
		if not pin_names or any(not pin_name for pin_name in pin_names):
			raise ValueError("--pins must contain comma-separated, non-empty pin names")
		if len(set(pin_names)) != len(pin_names):
			raise ValueError("--pins contains duplicate pin names")
		pins = tuple(
			ReferencePin(
				name=pin_name,
				logic_name="",
				pcb_pin=pin_name,
				scm_pin=pin_name,
			)
			for pin_name in pin_names
		)
		return ReferenceStructure(
			part_name=f"explicit:{arguments.symbol}/{arguments.footprint}",
			part_number="",
			name_stem=arguments.name_stem,
			footprint=arguments.footprint,
			symbol=arguments.symbol,
			pins=pins,
		)

	def _withNameStem(
		self,
		reference: ReferenceStructure,
		name_stem: str,
	) -> ReferenceStructure:
		if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name_stem):
			raise ValueError(f"Unsupported name stem {name_stem}")
		return ReferenceStructure(
			part_name=reference.part_name,
			part_number=reference.part_number,
			name_stem=name_stem,
			footprint=reference.footprint,
			symbol=reference.symbol,
			pins=reference.pins,
		)

	def _readRows(self, parts_csv_path: Path) -> list[dict[str, str]]:
		with parts_csv_path.open("r", encoding="utf-8-sig", newline="") as source_file:
			reader = csv.DictReader(source_file)
			if not reader.fieldnames:
				raise ValueError(f"CSV {parts_csv_path} does not contain a header")
			rows = [
				{
					str(column_name).strip(): str(column_value or "").strip()
					for column_name, column_value in row.items()
				}
				for row in reader
				if any(str(column_value or "").strip() for column_value in row.values())
			]
		if not rows:
			raise ValueError(f"CSV {parts_csv_path} does not contain any part rows")
		return rows

	def _generateFiles(
		self,
		reference: ReferenceStructure,
		rows: list[dict[str, str]],
		output_directory: Path,
		include_reference: bool,
	) -> list[Path]:
		created_paths: list[Path] = []
		seen_names: set[str] = set()
		for row in rows:
			part_name = self._getField(row, "Pulsonix part name", "Part Name", "Name")
			part_number = self._getField(
				row,
				"Manufacturer part number",
				"Manufacturer Part Number",
				"Part Number",
				"MPN",
			)
			if not part_name or not part_number:
				raise ValueError(
					"Every CSV row needs Pulsonix part name and Manufacturer part number"
				)
			if not include_reference and reference.part_number and part_number == reference.part_number:
				self.logger.info(f"Skipped reference MPN {part_number}")
				continue
			if part_name in seen_names:
				raise ValueError(f"Duplicate Pulsonix part name in CSV: {part_name}")
			seen_names.add(part_name)

			requested_footprint = self._getField(
				row,
				"Pulsonix footprint",
				"Footprint",
			)
			if (
				requested_footprint
				and requested_footprint.casefold() != reference.footprint.casefold()
			):
				raise ValueError(
					f"Part {part_name} requests footprint {requested_footprint}, but structure "
					f"{reference.part_name} uses footprint {reference.footprint}"
				)
			requested_symbol = self._getField(row, "Symbol")
			if requested_symbol and requested_symbol.casefold() != reference.symbol.casefold():
				self.logger.warning(
					f"Ignored CSV symbol {requested_symbol} for {part_name}; "
					f"the verified reference uses {reference.symbol}"
				)

			attributes = self._attributesFromRow(row, part_number, reference.footprint)
			description = self._descriptionFromRow(row, attributes)
			plx_text = self._buildPlx(reference, part_name, description, attributes)
			file_name = INVALID_FILENAME_PATTERN.sub("_", part_name).rstrip(". ")
			if not file_name:
				raise ValueError(f"Part name {part_name} cannot be represented as a file name")
			output_path = output_directory / f"{file_name}.plx"
			output_path.write_text(plx_text, encoding="utf-8", newline="\n")
			created_paths.append(output_path)
		return created_paths

	def _attributesFromRow(
		self,
		row: dict[str, str],
		part_number: str,
		footprint: str,
	) -> dict[str, str]:
		value = self._getField(row, "Value")
		if not value:
			value = self._formatResistance(self._getField(row, "Value (ohm)"))
		if not value:
			value = self._formatResistance(self._getField(row, "Resistance"))
		if not value:
			value = self._getField(row, "Capacitance", "Inductance")
		manufacturer = self._getField(row, "Manufacturer")

		attributes: dict[str, str] = {
			"Part Number": part_number,
			"Manufacturer": manufacturer,
			"Value": self._normaliseText(value),
			"Tolerance": "",
			"Voltage Rating": "",
			"Current Rating": "",
			"Power Rating": "",
			"Package": self._normaliseText(self._getField(row, "Package") or footprint),
		}
		column_mapping = (
			("LCSC Part Number", ("LCSC part number", "LCSC Part Number", "LCSC")),
			("Power Rating", ("Power Rating", "Power(Watts)")),
			("Tolerance", ("Tolerance",)),
			("Voltage Rating", ("Voltage Rating", "Voltage-Supply(Max)")),
			("Temperature Coefficient", ("Temperature Coefficient",)),
			("Operating Temperature", ("Operating Temperature",)),
			("Technology", ("Technology", "Type")),
			("Dielectric", ("Dielectric", "Temperature Characteristic")),
			("Current Rating", ("Current Rating",)),
			("<Hyperlink>", ("<Hyperlink>", "Datasheet", "Datasheet URL")),
		)
		for attribute_name, column_names in column_mapping:
			attribute_value = self._getField(row, *column_names)
			if attribute_value:
				attributes[attribute_name] = self._normaliseAttribute(
					attribute_name,
					attribute_value,
				)
		for column_name, column_value in row.items():
			if column_name.casefold().startswith("attribute:") and column_value:
				attribute_name = column_name.split(":", 1)[1].strip()
				if attribute_name:
					attributes[attribute_name] = self._normaliseText(column_value)
		return attributes

	def _descriptionFromRow(
		self,
		row: dict[str, str],
		attributes: dict[str, str],
	) -> str:
		description = self._getField(row, "Description")
		if description:
			return self._normaliseText(description)
		fragments = [
			attributes.get("Manufacturer", ""),
			attributes.get("Package", ""),
			attributes.get("Technology", ""),
			attributes.get("Value", ""),
			attributes.get("Tolerance", ""),
			attributes.get("Power Rating", ""),
			attributes.get("Voltage Rating", ""),
			attributes.get("Temperature Coefficient", ""),
			attributes.get("Operating Temperature", ""),
		]
		return ", ".join(fragment for fragment in fragments if fragment)

	def _buildPlx(
		self,
		reference: ReferenceStructure,
		part_name: str,
		description: str,
		attributes: dict[str, str],
	) -> str:
		quoted_name = self._quote(part_name)
		lines = [
			f"PULSONIX_LIBRARY_ASCII {quoted_name}",
			"(asciiHeader (fileUnits MM))",
			"(library Generated_Variants",
			f"  (compDef {quoted_name} (originalName {quoted_name})",
			f"    (compHeader (numPins {len(reference.pins)}) (numParts 1) "
			f"(refDesPrefix {reference.name_stem}))",
		]
		for symbol_pin_number, pin in enumerate(reference.pins, 1):
			lines.append(
				f"    (compPin {self._quote(pin.name)} "
				f"(pinName {self._quote(pin.logic_name)}) (partNum 1) "
				f"(symPinNum {symbol_pin_number}) (gateEq 0) (pinEq 0) "
				"(pinType Unknown))"
			)
		lines.extend(
			(
				f"    (attachedSymbol (partNum 1) (altType Normal) "
				f"(symbolName {self._quote(reference.symbol)}))",
				f"    (attachedPattern (patternNum 1) "
				f"(patternName {self._quote(reference.footprint)})",
				f"      (numPads {len(reference.pins)})",
				"      (padPinMap",
			)
		)
		for pin in reference.pins:
			lines.append(
				f"        (padNum {self._quote(pin.pcb_pin)}) "
				f"(compPinRef {self._quote(pin.name)})"
			)
		lines.extend(("      )", "    )"))
		if description:
			lines.append(f"    (attr \"Description\" {self._quote(description)})")
		for attribute_name, attribute_value in attributes.items():
			lines.append(
				f"    (attr {self._quote(attribute_name)} {self._quote(attribute_value)})"
			)
		lines.extend(("  )", ")", ""))
		return "\n".join(lines)

	def _getField(self, row: dict[str, str], *column_names: str) -> str:
		casefolded_row = {column_name.casefold(): value for column_name, value in row.items()}
		for column_name in column_names:
			value = casefolded_row.get(column_name.casefold(), "")
			if value:
				return value
		return ""

	def _formatResistance(self, raw_value: str) -> str:
		if not raw_value:
			return ""
		clean_value = (
			raw_value.replace("\u03a9", "")
			.replace("ohms", "")
			.replace("Ohms", "")
			.replace("ohm", "")
			.replace("Ohm", "")
			.strip()
		)
		match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([kKmM]?)", clean_value)
		if not match:
			return self._normaliseText(raw_value)
		try:
			value = Decimal(match.group(1))
		except InvalidOperation:
			return self._normaliseText(raw_value)
		multiplier = match.group(2).casefold()
		if multiplier == "k":
			value *= Decimal("1000")
		elif multiplier == "m":
			value *= Decimal("1000000")
		if value >= Decimal("1000000"):
			return f"{self._formatDecimal(value / Decimal('1000000'))}M"
		if value >= Decimal("1000"):
			return f"{self._formatDecimal(value / Decimal('1000'))}k"
		return f"{self._formatDecimal(value)}R"

	def _formatDecimal(self, value: Decimal) -> str:
		formatted_value = format(value.normalize(), "f")
		if "." in formatted_value:
			formatted_value = formatted_value.rstrip("0").rstrip(".")
		return formatted_value or "0"

	def _normaliseAttribute(self, attribute_name: str, raw_value: str) -> str:
		value = self._normaliseText(raw_value)
		if attribute_name == "Power Rating":
			match = POWER_MILLIWATT_PATTERN.match(value)
			if match:
				watts = Decimal(match.group(1)) / Decimal("1000")
				return f"{self._formatDecimal(watts)}W"
		if attribute_name == "Tolerance":
			return value.removeprefix("+/-")
		return value

	def _normaliseText(self, raw_value: str) -> str:
		return (
			raw_value.replace("\u00b1", "+/-")
			.replace("\u2103", "C")
			.replace("\u00b0C", "C")
			.replace("~", " to ")
			.strip()
		)

	def _quote(self, value: str) -> str:
		clean_value = value.replace("\r", " ").replace("\n", " ")
		clean_value = clean_value.replace("\\", "\\\\").replace("\"", "\\\"")
		return f"\"{clean_value}\""


def parseArguments() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description=(
			"Generate single-gate component PLX variants from an enriched CSV, using "
			"either a read-only reference part or explicit symbol and footprint names."
		)
	)
	parser.add_argument("--library", help="Path to the native .pal library for reference mode")
	parser.add_argument("--reference", help="Existing reference part name")
	parser.add_argument("--symbol", help="Existing symbol name for explicit structure mode")
	parser.add_argument("--footprint", help="Existing footprint name for explicit structure mode")
	parser.add_argument(
		"--name-stem",
		help=(
			"Reference designator prefix; required in explicit mode and overrides the "
			"reference part in reference mode"
		),
	)
	parser.add_argument(
		"--pins",
		help="Comma-separated identity pin map for explicit mode, for example 1,2",
	)
	parser.add_argument("--parts-csv", required=True, help="Source or MCP-enriched CSV")
	parser.add_argument("--output", required=True, help="Directory for generated PLX files")
	parser.add_argument(
		"--include-reference",
		action="store_true",
		help="Generate a PLX even when a row has the reference part's MPN",
	)
	return parser.parse_args()


def main() -> int:
	return VariantPlxGenerator.getInstance().run(parseArguments())


if __name__ == "__main__":
	sys.exit(main())
