"""Rename existing .pal attribute names offline, preserving values and object IDs."""

import argparse
import logging
from pathlib import Path
import sys

from modules.library_attribute_rename import LibraryAttributeRenamer


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--version", action="version", version="%(prog)s 1.0")
	parser.add_argument("--library", type=Path, required=True, help="Existing .pal library; its .palx must be present")
	parser.add_argument("--rename", action="append", required=True, metavar="OLD=NEW", help="Exact attribute names; repeat for independent pairs")
	parser.add_argument("--output", type=Path, required=True, help="New directory for the staged copy and audit reports")
	parser.add_argument("--publish", action="store_true", help="Back up the current pair and install the verified edit in the original library")
	arguments = parser.parse_args()
	logging.basicConfig(level=logging.INFO, format="%(message)s")
	logger = logging.getLogger("pulsonix.library_attribute_rename")
	try:
		renames = {}
		for value in arguments.rename:
			if "=" not in value:
				raise ValueError(f"Use --rename OLD=NEW; received {value!r}")
			source, target = value.split("=", 1)
			if source in renames:
				raise ValueError(f"Duplicate source name: {source}")
			renames[source] = target
		report = LibraryAttributeRenamer(arguments.library, renames, arguments.output).execute(arguments.publish)
		logger.info("%s: %s definitions renamed across %s/%s parts; %s parts contain identical destination records", report["status"], report["renamed_definitions"], report["changed_parts"], report["part_count"], report["parts_with_identical_duplicates"])
		if report.get("backup"):
			logger.info("Backup: %s", report["backup"])
		logger.info("Offline verification only; Pulsonix loading was not tested")
		return 0
	except KeyboardInterrupt:
		logger.error("Interrupted; inspect the output audit before retrying publication")
		return 130
	except Exception as error:
		logger.error("Offline rename stopped because %s", error)
		return 1


if __name__ == "__main__":
	sys.exit(main())
