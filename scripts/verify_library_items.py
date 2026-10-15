"""Verify exact symbol and footprint names in Pulsonix index files."""

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import sys

from modules.runtime import RuntimeSupport


@dataclass(frozen=True)
class LibraryIndexItem:
	"""Name and pin count read from one Pulsonix library index row."""

	name: str
	pin_count: int


class LibraryItemVerifier:
	"""Check structural links before generating a part without a reference."""

	_instance: "LibraryItemVerifier | None" = None

	def __init__(self) -> None:
		self.runtime = RuntimeSupport.getInstance()
		self.logger = self.runtime.configureLogging("pulsonix.verify_library_items")

	@classmethod
	def getInstance(cls) -> "LibraryItemVerifier":
		if cls._instance is None:
			cls._instance = cls()
		return cls._instance

	def run(self, arguments: argparse.Namespace) -> int:
		try:
			expected_pin_count = arguments.expected_pins
			if expected_pin_count < 1:
				raise ValueError("--expected-pins must be at least 1")
			symbol = self._findExactItem(
				Path(arguments.symbol_index),
				arguments.symbol,
				"symbol",
			)
			footprint = self._findExactItem(
				Path(arguments.footprint_index),
				arguments.footprint,
				"footprint",
			)
			for item_type, item in (("symbol", symbol), ("footprint", footprint)):
				if item.pin_count != expected_pin_count:
					raise ValueError(
					f"{item_type.title()} {item.name} has {item.pin_count} pins, "
					f"expected {expected_pin_count}"
				)
			self.logger.info(
				f"Verified symbol {symbol.name} and footprint {footprint.name} "
				f"with {expected_pin_count} pins"
			)
			return 0
		except Exception as error:
			self.logger.error(f"Library item verification failed because {error}")
			return 1

	def _findExactItem(
		self,
		index_path: Path,
		requested_name: str,
		item_type: str,
	) -> LibraryIndexItem:
		if not index_path.is_file():
			raise FileNotFoundError(f"{item_type.title()} index {index_path} does not exist")
		with index_path.open("r", encoding="utf-8-sig", newline="") as index_file:
			reader = csv.reader(index_file, delimiter="\t")
			next(reader, None)
			for row_number, row in enumerate(reader, 2):
				if not row or row[0] != requested_name:
					continue
				if len(row) < 2:
					raise ValueError(
						f"{item_type.title()} index row {row_number} has no pin count"
					)
				try:
					pin_count = int(row[1])
				except Exception as error:
					raise ValueError(
						f"{item_type.title()} index row {row_number} has invalid pin "
						f"count {row[1]}"
					) from error
				return LibraryIndexItem(name=row[0], pin_count=pin_count)
		raise KeyError(
			f"Exact {item_type} name {requested_name} is absent from {index_path}"
		)


def parseArguments() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description=(
			"Verify exact symbol and footprint names and pin counts before explicit "
			"component PLX generation."
		)
	)
	parser.add_argument("--symbol-index", required=True, help="Path to the .sslx file")
	parser.add_argument("--symbol", required=True, help="Exact existing symbol name")
	parser.add_argument(
		"--footprint-index",
		required=True,
		help="Path to the .pflx file",
	)
	parser.add_argument("--footprint", required=True, help="Exact footprint name")
	parser.add_argument(
		"--expected-pins",
		required=True,
		type=int,
		help="Required pin count for both items",
	)
	return parser.parse_args()


def main() -> int:
	return LibraryItemVerifier.getInstance().run(parseArguments())


if __name__ == "__main__":
	sys.exit(main())
