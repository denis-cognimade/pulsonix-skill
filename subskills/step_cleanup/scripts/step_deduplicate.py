"""Run the final instancing stage on an already cleaned direct-BRep STEP export."""

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def runDeduplication(source: Path, output: Path) -> dict:
	from modules.step_instancing import deduplicateCandidate
	if source.resolve() == output.resolve() or output.exists():
		raise ValueError("Choose a new output path distinct from the source")
	report_path = output.with_suffix(f"{output.suffix}.instancing.json")
	if report_path.exists():
		raise ValueError(f"Report already exists: {report_path}")
	with tempfile.TemporaryDirectory(prefix=".step_instancing_", dir=output.parent) as temporary:
		candidate = Path(temporary) / "candidate.stp"
		report = deduplicateCandidate(source, candidate)
		report.update({"source": str(source), "output": str(output)})
		from modules.instancing_audit import digest
		if digest(source) != report["source_sha256"] or output.exists() or report_path.exists():
			raise ValueError("Source changed or output/report appeared during instancing")
		report_temporary = Path(temporary) / "report.json"
		report_temporary.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
		os.replace(candidate, output)
		os.replace(report_temporary, report_path)
		logger.info("Published %s; report %s", output, report_path)
		return report


def main() -> int:
	parser = argparse.ArgumentParser(description="Deduplicate cleaned STEP solids with shared geometry, preserving products, placements, and appearance.")
	parser.add_argument("--version", action="version", version="step_deduplicate 1.0.0")
	parser.add_argument("source", type=Path, help="Cleaned direct-BRep .stp or .step input")
	parser.add_argument("--output", type=Path, help="New output path; default SOURCE_instanced.stp")
	args = parser.parse_args()
	source = args.source.resolve()
	output = args.output.resolve() if args.output else source.with_name(f"{source.stem}_instanced{source.suffix}")
	if not source.is_file() or source.suffix.lower() not in {".stp", ".step"}:
		parser.error("source must be an existing .stp or .step file")
	if output.suffix.lower() not in {".stp", ".step"} or not output.parent.is_dir():
		parser.error("output must be a .stp/.step path in an existing directory")
	if output == source or output.exists():
		parser.error("choose a new output path distinct from the source")
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
	try:
		runDeduplication(source, output)
		return 0
	except KeyboardInterrupt:
		logger.error("Instancing interrupted; no unvalidated STEP was published")
		return 130
	except Exception as error:
		logger.error("Instancing failed: %s", error)
		return 1


if __name__ == "__main__":
	raise SystemExit(main())
