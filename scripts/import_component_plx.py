"""Back up and import component PLX files through standard Pulsonix APIs."""

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import shutil
import sys

from modules.library_access import NativeLibraryAccess
from modules.part_snapshot import PartSnapshotReader
from modules.pipe_client import PulsonixPipeClient
from modules.runtime import RuntimeSupport


QUOTED_TEXT = r'"((?:\\.|[^"\\])*)"'
COMPONENT_NAME_PATTERN = re.compile(rf"\(compDef\s+{QUOTED_TEXT}")
PIN_COUNT_PATTERN = re.compile(r"\(compHeader\s+\(numPins\s+(\d+)\)")
SYMBOL_PATTERN = re.compile(rf"\(attachedSymbol.*?\(symbolName\s+{QUOTED_TEXT}\)\)")
FOOTPRINT_PATTERN = re.compile(rf"\(attachedPattern.*?\(patternName\s+{QUOTED_TEXT}\)")
ATTRIBUTE_PATTERN = re.compile(rf"\(attr\s+{QUOTED_TEXT}\s+{QUOTED_TEXT}\)")


@dataclass(frozen=True)
class PlxExpectation:
	"""Fields that must match after a component PLX import."""

	path: Path
	name: str
	pin_count: int
	symbol: str
	footprint: str
	description: str
	attributes: dict[str, str]


class ComponentPlxImporter:
	"""Perform a guarded standard-license import and readback."""

	_instance: "ComponentPlxImporter | None" = None

	def __init__(self) -> None:
		self.runtime = RuntimeSupport.getInstance()
		self.logger = self.runtime.configureLogging("pulsonix.import_component_plx")
		self.reader = PartSnapshotReader.getInstance()
		self.backup_directory: Path | None = None
		self.imported_names: list[str] = []
		self.active_import_name: str | None = None

	@classmethod
	def getInstance(cls) -> "ComponentPlxImporter":
		if cls._instance is None:
			cls._instance = cls()
		return cls._instance

	def run(self, arguments: argparse.Namespace) -> int:
		try:
			library_path = Path(arguments.library).resolve()
			plx_directory = Path(arguments.plx_directory).resolve()
			if not library_path.is_file():
				raise FileNotFoundError(
					f"Component import failed because {library_path} does not exist"
				)
			if library_path.suffix.casefold() != ".pal":
				raise ValueError("Component import requires a native .pal library")
			if not plx_directory.is_dir():
				raise FileNotFoundError(
					f"Component import failed because {plx_directory} does not exist"
				)

			NativeLibraryAccess.getInstance().requireWritableLibrary(library_path)

			expectations = [
				self._readExpectation(path)
				for path in sorted(plx_directory.glob("*.plx"))
			]
			if not expectations:
				raise ValueError(f"No PLX files were found in {plx_directory}")
			self._checkDuplicateNames(expectations)

			client = PulsonixPipeClient.getInstance()
			try:
				client.connect()
				self._rejectExistingParts(client, library_path, expectations)
				self.backup_directory = self._createBackup(
					library_path,
					Path(arguments.backup_directory).resolve()
					if arguments.backup_directory
					else None,
				)
				self.logger.info(f"Created backup in {self.backup_directory}")

				for expectation in expectations:
					self.active_import_name = expectation.name
					client.call(
						"AddToLibrary",
						str(expectation.path),
						1,
						str(library_path),
						False,
						timeout_seconds=120.0,
					)
					self.imported_names.append(expectation.name)
					self.active_import_name = None
					self.logger.info(f"Imported {expectation.name}")

				self._verifyImports(client, library_path, expectations)
				self.logger.info(
					f"Verified {len(expectations)} parts in {library_path}"
				)
				return 0
			finally:
				client.close()
		except Exception as error:
			context = ""
			if self.imported_names:
				context = f"; parts imported before failure: {self.imported_names}"
			if self.active_import_name is not None:
				context = (
					f"{context}; check whether {self.active_import_name} exists before retrying"
				)
			if self.backup_directory is not None:
				context = f"{context}; backup: {self.backup_directory}"
			self.logger.error(f"Component import failed because {error}{context}")
			return 1

	def _readExpectation(self, plx_path: Path) -> PlxExpectation:
		plx_text = plx_path.read_text(encoding="utf-8")
		name_match = COMPONENT_NAME_PATTERN.search(plx_text)
		pin_count_match = PIN_COUNT_PATTERN.search(plx_text)
		symbol_match = SYMBOL_PATTERN.search(plx_text)
		footprint_match = FOOTPRINT_PATTERN.search(plx_text)
		if not all((name_match, pin_count_match, symbol_match, footprint_match)):
			raise ValueError(f"PLX {plx_path} is missing a required component field")

		attributes: dict[str, str] = {}
		for attribute_match in ATTRIBUTE_PATTERN.finditer(plx_text):
			attribute_name = self._unescape(attribute_match.group(1))
			attribute_value = self._unescape(attribute_match.group(2))
			attributes[attribute_name] = attribute_value
		description = attributes.pop("Description", "")
		return PlxExpectation(
			path=plx_path,
			name=self._unescape(name_match.group(1)),
			pin_count=int(pin_count_match.group(1)),
			symbol=self._unescape(symbol_match.group(1)),
			footprint=self._unescape(footprint_match.group(1)),
			description=description,
			attributes=attributes,
		)

	def _checkDuplicateNames(self, expectations: list[PlxExpectation]) -> None:
		names = [expectation.name for expectation in expectations]
		duplicate_names = sorted({name for name in names if names.count(name) > 1})
		if duplicate_names:
			raise ValueError(f"Duplicate part names in PLX input: {duplicate_names}")

	def _rejectExistingParts(
		self,
		client: PulsonixPipeClient,
		library_path: Path,
		expectations: list[PlxExpectation],
	) -> None:
		library_id: int | None = None
		try:
			library_id = self._requireObjectId(
				client.call("OpenPartLibrary", str(library_path), True),
				"OpenPartLibrary",
			)
			existing_names = [
				expectation.name
				for expectation in expectations
				if client.call("Contains", expectation.name, object_id=library_id) is True
			]
			if existing_names:
				raise FileExistsError(
					f"Refusing to overwrite existing parts: {existing_names}"
				)
		finally:
			if library_id is not None:
				self._releaseObject(client, library_id)

	def _createBackup(
		self,
		library_path: Path,
		requested_directory: Path | None,
	) -> Path:
		timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
		backup_directory = requested_directory or (
			library_path.parent / f"backup_before_{library_path.stem}_{timestamp}"
		)
		if backup_directory.exists() and any(backup_directory.iterdir()):
			raise FileExistsError(
				f"Backup directory {backup_directory} already exists and is not empty"
			)
		backup_directory.mkdir(parents=True, exist_ok=True)
		shutil.copy2(library_path, backup_directory / library_path.name)
		index_path = library_path.with_suffix(".palx")
		if index_path.is_file():
			shutil.copy2(index_path, backup_directory / index_path.name)
		return backup_directory

	def _verifyImports(
		self,
		client: PulsonixPipeClient,
		library_path: Path,
		expectations: list[PlxExpectation],
	) -> None:
		library_id: int | None = None
		try:
			library_id = self._requireObjectId(
				client.call("OpenPartLibrary", str(library_path), True),
				"OpenPartLibrary",
			)
			for expectation in expectations:
				part = self.reader.readPartFromOpenLibrary(
					client,
					library_id,
					expectation.name,
				)
				actual_symbol = (
					part["gates"][0]["default_symbol"] if part["gates"] else ""
				)
				mismatches: dict[str, object] = {}
				self._recordMismatch(
					mismatches,
					"pin_count",
					expectation.pin_count,
					part["pin_count"],
				)
				self._recordMismatch(
					mismatches,
					"symbol",
					expectation.symbol,
					actual_symbol,
				)
				self._recordMismatch(
					mismatches,
					"footprint",
					expectation.footprint,
					part["default_footprint"],
				)
				self._recordMismatch(
					mismatches,
					"description",
					expectation.description,
					part["description"],
				)
				for attribute_name, expected_value in expectation.attributes.items():
					self._recordMismatch(
						mismatches,
						f"attribute:{attribute_name}",
						expected_value,
						part["attributes"].get(attribute_name),
					)
				if mismatches:
					raise RuntimeError(
						f"Readback mismatch for {expectation.name}: {mismatches}"
					)
		finally:
			if library_id is not None:
				self._releaseObject(client, library_id)

	def _releaseObject(self, client: PulsonixPipeClient, object_id: int) -> None:
		try:
			client.call("Delete", object_id)
		except Exception as error:
			self.logger.warning(
				f"Could not release Pulsonix object {object_id} because {error}"
			)

	def _requireObjectId(self, value: object, operation_name: str) -> int:
		if isinstance(value, bool) or not isinstance(value, int):
			raise RuntimeError(
				f"{operation_name} returned {type(value).__name__}, expected object ID"
			)
		return value

	def _recordMismatch(
		self,
		mismatches: dict[str, object],
		field_name: str,
		expected_value: object,
		actual_value: object,
	) -> None:
		if expected_value != actual_value:
			mismatches[field_name] = {
				"expected": expected_value,
				"actual": actual_value,
			}

	def _unescape(self, value: str) -> str:
		return re.sub(r"\\([\\\"])", r"\1", value)


def parseArguments() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description=(
			"Back up a .pal/.palx pair, import component PLX files with "
			"AddToLibrary, and verify every imported field."
		)
	)
	parser.add_argument("--library", required=True, help="Path to the target .pal library")
	parser.add_argument(
		"--plx-directory",
		required=True,
		help="Directory containing component-only PLX files",
	)
	parser.add_argument(
		"--backup-directory",
		help="Optional empty backup directory; a timestamped sibling is used by default",
	)
	return parser.parse_args()


def main() -> int:
	return ComponentPlxImporter.getInstance().run(parseArguments())


if __name__ == "__main__":
	sys.exit(main())
