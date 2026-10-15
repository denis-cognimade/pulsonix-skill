"""Inspect one Pulsonix part through read-only, standard-license API calls."""

import argparse
import json
from pathlib import Path
import sys

from modules.part_snapshot import PartSnapshotReader
from modules.runtime import RuntimeSupport


class PartInspector:
	"""Create a complete JSON snapshot of one native-library part."""

	_instance: "PartInspector | None" = None

	def __init__(self) -> None:
		self.runtime = RuntimeSupport.getInstance()
		self.logger = self.runtime.configureLogging("pulsonix.inspect_part")
		self.reader = PartSnapshotReader.getInstance()

	@classmethod
	def getInstance(cls) -> "PartInspector":
		if cls._instance is None:
			cls._instance = cls()
		return cls._instance

	def run(self, arguments: argparse.Namespace) -> int:
		try:
			library_path = Path(arguments.library)
			if not library_path.is_file():
				raise FileNotFoundError(
					f"Part inspection failed because {library_path} does not exist"
				)
			result = self.reader.readPart(library_path, arguments.part)
			output_path = Path(arguments.output).resolve()
			output_path.parent.mkdir(parents=True, exist_ok=True)
			output_path.write_text(
				json.dumps(result, indent=2, ensure_ascii=False),
				encoding="utf-8",
				newline="\n",
			)
			self.logger.info(f"Wrote part inspection to {output_path}")
			return 0
		except Exception as error:
			self.logger.error(f"Part inspection failed because {error}")
			return 1


def parseArguments() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Inspect one Pulsonix part without Advanced scripting operations."
	)
	parser.add_argument("--library", required=True, help="Path to the native .pal library")
	parser.add_argument("--part", required=True, help="Existing reference part name")
	parser.add_argument("--output", required=True, help="Destination JSON file")
	return parser.parse_args()


def main() -> int:
	return PartInspector.getInstance().run(parseArguments())


if __name__ == "__main__":
	sys.exit(main())
