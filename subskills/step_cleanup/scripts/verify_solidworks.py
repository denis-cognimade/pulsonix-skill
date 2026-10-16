"""Verify body counts and shared-solid placements in an existing SolidWorks session."""

import argparse
import hashlib
import json
import logging
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def expectedInventory(source: Path) -> tuple[dict, dict]:
	import cadquery as cq
	from OCP.TDF import TDF_Label, TDF_LabelSequence
	from modules.cad_geometry import CadModel

	model = CadModel(source, internal_labels=True)
	roots = TDF_LabelSequence()
	model.shape_tool.GetFreeShapes(roots)
	counts = {model.labelName(roots.Value(index)): len(cq.Shape.cast(model.shape_tool.GetShape_s(roots.Value(index))).Solids())
		for index in range(1, roots.Length() + 1)}
	placements = {}
	def visit(label: object, parent: cq.Location) -> None:
		location = parent * cq.Location(model.shape_tool.GetLocation_s(label))
		if model.shape_tool.IsReference_s(label):
			referred = TDF_Label()
			model.shape_tool.GetReferredShape_s(label, referred)
			visit(referred, location)
		elif model.shape_tool.IsAssembly_s(label):
			children = TDF_LabelSequence()
			model.shape_tool.GetComponents_s(label, children)
			for index in range(1, children.Length() + 1):
				visit(children.Value(index), location)
		else:
			name = model.labelName(label)
			if name.startswith("__STEP_SHARED_"):
				matrix = location.wrapped.Transformation()
				values = [matrix.Value(row + 1, column + 1) for column in range(3) for row in range(3)]
				values.extend(matrix.Value(row + 1, 4) / 1000 for row in range(3))
				placements.setdefault(name, []).append(values)
	for index in range(1, roots.Length() + 1):
		visit(roots.Value(index), cq.Location())
	return counts, placements


def verify(source: Path, report_path: Path) -> dict:
	import pythoncom
	import win32com.client
	from win32com.client import dynamic
	from modules.step_graph import StepGraph, TOKEN_PATTERN

	if report_path.exists() or report_path.resolve() == source.resolve():
		raise ValueError("Choose a new verification report path")
	source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
	counts, placements = expectedInventory(source)
	pythoncom.CoInitialize()
	def dispatchObject(raw: object, methods: tuple[str, ...]) -> object:
		item = dynamic.DumbDispatch(raw)
		for name in methods:
			item._FlagAsMethod(name)
		return item
	application = dispatchObject(win32com.client.GetActiveObject("SldWorks.Application"),
		("GetImportFileData", "LoadFile4", "GetDocuments", "CloseDoc", "ActivateDoc3", "RevisionNumber"))
	previous = application.ActiveDoc
	previous_title = dispatchObject(previous, ("GetTitle",)).GetTitle() if previous else None
	before_titles = {dispatchObject(document, ("GetTitle",)).GetTitle() for document in application.GetDocuments() or []}
	prefix = f"verify_{uuid.uuid4().hex[:8]}_"
	report = {"source": str(source.resolve()), "source_sha256": source_hash, "status": "failed",
		"solidworks_revision": application.RevisionNumber(), "expected_solids": sum(counts.values()),
		"expected_component_solid_counts": counts, "components": []}
	try:
		with tempfile.TemporaryDirectory(prefix="verify_sw_step_") as temporary:
			graph = StepGraph(source)
			for entity_id, value in list(graph.entities.items()):
				if value.startswith(("PRODUCT(", "NEXT_ASSEMBLY_USAGE_OCCURRENCE(")):
					graph.entities[entity_id] = TOKEN_PATTERN.sub(lambda match: match.group(0) if match.group(1) else f"'{prefix}{match.group(0)[1:-1]}'", value)
			path = Path(temporary) / f"{prefix}board.step"
			graph.write(path)
			logger.info("Importing isolated STEP copy into SolidWorks")
			import_data = application.GetImportFileData(str(path))
			errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
			raw_document = application.LoadFile4(str(path), "r", import_data, errors)
			report["import_error"] = errors.value
			if raw_document is None:
				raise ValueError(f"SolidWorks STEP import failed: {errors.value}")
			document = dispatchObject(raw_document, ("GetType",))
			components = []
			if document.GetType() == 1:
				components.append((next(iter(counts)), document, None))
			else:
				document._FlagAsMethod("GetComponents")
				for raw_component in document.GetComponents(False) or []:
					component = dispatchObject(raw_component, ("GetModelDoc2",))
					part = component.GetModelDoc2()
					if part is None:
						raise ValueError(f"Unresolved imported component: {component.Name2}")
					part = dispatchObject(part, ("GetType",))
					if part.GetType() == 1:
						components.append((component.Name2, part, dynamic.DumbDispatch(component.Transform2).ArrayData))
			actual_counts = {}
			rotation_errors = []
			translation_errors = []
			for name, part, matrix in components:
				part._FlagAsMethod("GetBodies2")
				body_count = len(part.GetBodies2(0, False) or [])
				record = {"name": name, "solids": body_count, "transform": matrix}
				report["components"].append(record)
				root_name = name.removeprefix(prefix).split("/")[0].rsplit("-", 1)[0]
				actual_counts[root_name] = actual_counts.get(root_name, 0) + body_count
				prototype = name.split("/")[-1].removeprefix(prefix).rsplit("-", 1)[0]
				if prototype.startswith("__STEP_SHARED_"):
					options = placements.get(prototype, [])
					if not options or matrix is None or body_count != 1:
						raise ValueError(f"Missing or incorrect shared solid: {name}")
					best = min(range(len(options)), key=lambda index: sum(abs(left - right) for left, right in zip(options[index], matrix[:12])))
					expected = options.pop(best)
					rotation_errors.append(max(abs(left - right) for left, right in zip(expected[:9], matrix[:9])))
					translation_errors.append(1000 * max(abs(left - right) for left, right in zip(expected[9:12], matrix[9:12])))
			report.update({"actual_solids": sum(record["solids"] for record in report["components"]),
				"actual_component_solid_counts": actual_counts, "shared_occurrences_checked": len(rotation_errors),
				"maximum_rotation_matrix_error": max(rotation_errors, default=0),
				"maximum_translation_error_mm": max(translation_errors, default=0)})
			if report["actual_solids"] != report["expected_solids"]:
				raise ValueError(f"SolidWorks lost bodies: expected {report['expected_solids']}, imported {report['actual_solids']}")
			if len(counts) > 1 and actual_counts != counts:
				raise ValueError("SolidWorks component body counts differ from the STEP inventory")
			if any(placements.values()) or report["maximum_rotation_matrix_error"] > 1e-8 or report["maximum_translation_error_mm"] > 1e-5:
				raise ValueError("Shared solid placements differ in SolidWorks")
			if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
				raise ValueError("Verification source changed")
			report["status"] = "passed"
	except Exception as error:
		report["error"] = str(error)
		raise
	finally:
		try:
			for raw_document in application.GetDocuments() or []:
				document = dispatchObject(raw_document, ("GetTitle",))
				title = document.GetTitle()
				if title.startswith(prefix) and title not in before_titles:
					application.CloseDoc(title)
			if previous_title:
				errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
				application.ActivateDoc3(previous_title, False, 0, errors)
		except Exception as cleanup_error:
			report["session_cleanup_error"] = str(cleanup_error)
		report_path.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
	return report


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("source", type=Path)
	parser.add_argument("--report", type=Path, required=True)
	args = parser.parse_args()
	logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
	try:
		report = verify(args.source.resolve(), args.report.resolve())
		logger.info("SolidWorks passed: %d solids; %d shared placements checked", report["actual_solids"], report["shared_occurrences_checked"])
		return 0
	except Exception as error:
		logger.error("SolidWorks verification failed: %s", error)
		return 1


if __name__ == "__main__":
	raise SystemExit(main())
