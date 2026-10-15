"""Map embedded properties or generate an edit plan from a hash-bound calibration."""

import argparse
from pathlib import Path
import sys

from modules.native_editor import NativeEditor
from modules.native_plan import ArchiveProfile, PropertyChanges
from modules.native_properties import NativeProperties
from modules.runtime import RuntimeSupport


def main() -> int:
	logger = RuntimeSupport.getInstance().configureLogging("pulsonix.native_properties")
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source", type=Path, required=True)
	parser.add_argument("--profile", type=Path, required=True)
	parser.add_argument("--output", type=Path, required=True, help="New map or plan JSON")
	parser.add_argument("--changes", type=Path, help="Existing-property changes; generates a plan instead of a map")
	arguments = parser.parse_args()
	try:
		profile = ArchiveProfile.model_validate_json(arguments.profile.read_text(encoding="utf-8-sig"))
		source_bytes = arguments.source.read_bytes()
		if arguments.changes:
			changes = PropertyChanges.model_validate_json(arguments.changes.read_text(encoding="utf-8-sig"))
			result = NativeProperties.makePlan(source_bytes, profile, changes).model_dump(mode="json")
		else:
			result = NativeProperties.mapParts(source_bytes, profile)
		if arguments.source.read_bytes() != source_bytes:
			raise ValueError("Source changed during mapping")
		NativeEditor.writeJson(arguments.output, result)
		logger.info("Wrote %s", arguments.output)
		return 0
	except Exception as error:
		logger.error("Property mapping stopped because %s", error)
		return 1


if __name__ == "__main__":
	sys.exit(main())
