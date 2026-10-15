"""Offline typed .sch edits; prepare/verify/publish are separate operations."""

import argparse
from pathlib import Path
import sys

from modules.native_editor import NativeEditor
from modules.native_plan import NativeAudit, NativeEditPlan
from modules.runtime import RuntimeSupport


def main() -> int:
	logger = RuntimeSupport.getInstance().configureLogging("pulsonix.native_editor")
	parser = argparse.ArgumentParser(description=__doc__)
	subparsers = parser.add_subparsers(dest="operation", required=True)
	for operation in ("prepare", "verify", "publish"):
		command = subparsers.add_parser(operation)
		command.add_argument("--source", type=Path, required=True)
		command.add_argument("--candidate", type=Path, required=True)
		command.add_argument("--audit", type=Path, required=True)
		if operation == "prepare":
			command.add_argument("--plan", type=Path, required=True)
		if operation == "publish":
			command.add_argument("--backup", type=Path, required=True)
			command.add_argument("--in-place", action="store_true",
				help="Keep the original file object; interruption can leave a partial file")
	arguments = parser.parse_args()
	try:
		if arguments.operation == "prepare":
			plan = NativeEditPlan.model_validate_json(arguments.plan.read_text(encoding="utf-8-sig"))
			NativeEditor.prepare(arguments.source, arguments.candidate, arguments.audit, plan)
			logger.info("Candidate and audit prepared; original untouched: %s", arguments.candidate)
		elif arguments.operation == "verify":
			audit = NativeAudit.model_validate_json(arguments.audit.read_text(encoding="utf-8-sig"))
			NativeEditor.verify(arguments.source, arguments.candidate, audit)
			logger.info("Exact planned edits and all compound streams verified")
		else:
			audit = NativeEditor.publish(arguments.source, arguments.candidate, arguments.audit,
				arguments.backup, arguments.in_place)
			logger.info("Published %s; backup: %s", arguments.source, audit.backup)
		return 0
	except Exception as error:
		logger.error("Native edit stopped because %s", error)
		if arguments.operation == "publish" and arguments.backup.is_file():
			logger.error("Immediate backup retained at %s; inspect the original before retrying", arguments.backup)
		return 1


if __name__ == "__main__":
	sys.exit(main())
