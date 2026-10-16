"""Retain stage findings and rejected candidates without publishing failed cleanup."""

import hashlib
import json
import logging
import shutil
import tempfile
import traceback
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from .cad_geometry import HoleRemovalError

logger = logging.getLogger(__name__)


def writeJson(path: Path, value: dict | list) -> None:
	path.write_text(json.dumps(value, indent=2), encoding="utf-8", newline="\n")


class CleanupDiagnostics:
	def __init__(self, source: Path, output: Path, work: Path, options: dict) -> None:
		self.source = source
		self.output = output
		self.work = work
		self.report = {"status": "running", "published": False, "source": str(source), "output": str(output),
			"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "options": options,
			"stage": "schema", "product": None, "completed_stages": [], "findings": {}}

	def __enter__(self) -> "CleanupDiagnostics":
		return self

	def stage(self, name: str, product: str | None = None) -> None:
		self.report.update({"stage": name, "product": product})
		self.checkpoint()

	def passed(self, name: str, finding: dict | None = None) -> None:
		self.report["completed_stages"].append(name)
		if finding is not None:
			self.report["findings"][name] = finding
		self.checkpoint()

	def checkpoint(self) -> None:
		writeJson(self.work / "progress.json", self.report)

	def __exit__(self, error_type: type | None, error: BaseException | None, trace: TracebackType | None) -> bool:
		if error is None:
			return False
		# This executes before TemporaryDirectory removes the working files.
		try:
			self.report.update({"status": "failed", "error_type": type(error).__name__, "error": str(error),
				"traceback": "".join(traceback.format_exception(error_type, error, trace))})
			try:
				self.report["source_sha256_after"] = hashlib.sha256(self.source.read_bytes()).hexdigest()
				self.report["source_unchanged"] = self.report["source_sha256"] == self.report["source_sha256_after"]
			except Exception as hash_error:
				self.report.update({"source_unchanged": None, "source_hash_error": str(hash_error)})
			self.checkpoint()
			destination = Path(tempfile.mkdtemp(prefix=f"{self.output.name}.failed.", dir=self.output.parent))
			shutil.copytree(self.work, destination, dirs_exist_ok=True)
			self.report["artifacts"] = [{"path": str(path.relative_to(destination)), "bytes": path.stat().st_size,
				"sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(destination.rglob("*")) if path.is_file()]
			self.report["artifact_notice"] = "Diagnostic files only. Candidates may be partial, invalid, or unverified; do not publish them."
			writeJson(destination / "failure.json", self.report)
			if hasattr(error, "add_note"):
				error.add_note(f"Cleanup diagnostics: {destination / 'failure.json'}")
			logger.error("Cleanup failed at %s for %s; diagnostics: %s", self.report["stage"], self.report["product"], destination / "failure.json")
		except Exception as diagnostic_error:
			logger.error("Could not save cleanup diagnostics: %s (original error: %s)", diagnostic_error, error)
		return False


def saveHoleFailure(error: "HoleRemovalError", directory: Path, diagnose_bores: bool) -> dict:
	"""Save the part, selected faces and optional independent per-bore trials."""
	import cadquery as cq
	from .cad_geometry import HoleRemover, boreFaces, completeGroups, holeKeys

	directory.mkdir()
	details = dict(error.details)
	details["artifact_errors"] = []
	def exportShape(shape: cq.Shape, name: str) -> None:
		try:
			cq.exporters.export(shape, str(directory / name), exportType="STEP")
		except Exception as export_error:
			details["artifact_errors"].append({"path": name, "error": str(export_error)})
	try:
		exportShape(error.original, "original_part.stp")
		if error.candidate is not None:
			exportShape(error.candidate, "rejected_part.stp")
		faces = error.original.Faces()
		indices = details.get("selected_face_indices", [])
		details["selected_faces"] = [{"face_index": index, "surface": faces[index].geomType(),
			"area_mm2": faces[index].Area(), "center_mm": faces[index].Center().toTuple()} for index in indices]
		if indices:
			exportShape(cq.Compound.makeCompound([faces[index] for index in indices]), "selected_faces.stp")
		writeJson(directory / "bores.json", details)
		if diagnose_bores:
			remover = HoleRemover(details["diameter_limit_mm"])
			trials = []
			# Each trial starts from the same original, never from a partial result.
			for index, group in enumerate(completeGroups(boreFaces(error.original, remover.diameter))):
				logger.info("Diagnostic bore %d / %d: diameter %.9g mm", index + 1, len(details["selected_bores"]), group[0]["diameter"])
				trial = {"bore": details["selected_bores"][index], "status": "failed"}
				try:
					selected = remover.selectedFaces(error.original, [group])
					trial["selected_face_indices"] = sorted(selected)
					candidate, trial["operation"] = remover.defeature(error.original, selected)
					trial.update(remover.checkResult(error.original, candidate, require_all=False))
					remaining = completeGroups(boreFaces(candidate, remover.diameter))
					trial["target_absent"] = holeKeys([group])[0] not in holeKeys(remaining)
					trial["status"] = "diagnostic_pass" if trial["accepted"] and trial["target_absent"] else "rejected"
					exportShape(candidate, f"bore_{index:03d}_candidate.stp")
				except Exception as trial_error:
					trial["error"] = str(trial_error)
				trials.append(trial)
				writeJson(directory / "trials.json", trials)
	except Exception as diagnostic_error:
		details["artifact_errors"].append({"error": str(diagnostic_error)})
	writeJson(directory / "bores.json", details)
	return details
