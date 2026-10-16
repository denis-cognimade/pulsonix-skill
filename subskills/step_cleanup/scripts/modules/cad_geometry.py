"""Open CASCADE inspection and small-hole removal, adapted from the carrier cleanup."""

import collections
import logging
import math
from pathlib import Path
from typing import Callable

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.StepToTopoDS import StepToTopoDS_Builder
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_AttributeIterator, TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool

logger = logging.getLogger(__name__)
DIAMETER_EPSILON_MM = 1e-7


def boreFaces(shape: cq.Shape, diameter_limit: float = math.inf) -> list[dict]:
	bores = []
	for face_index, face in enumerate(shape.Faces()):
		surface = BRepAdaptor_Surface(face.wrapped, True)
		if surface.GetType() != GeomAbs_Cylinder:
			continue
		cylinder = surface.Cylinder()
		diameter = 2 * cylinder.Radius()
		if diameter >= diameter_limit - DIAMETER_EPSILON_MM:
			continue
		axis = cylinder.Axis()
		point = surface.Value((surface.FirstUParameter() + surface.LastUParameter()) / 2,
			(surface.FirstVParameter() + surface.LastVParameter()) / 2)
		# A STEP cylinder can have an indirect frame. Orientation alone then gives
		# the wrong answer; classify the actual outward face normal against its radius.
		normal = face.normalAt(cq.Vector(point.Coord())).toTuple()
		offset = [point.Coord()[index] - axis.Location().Coord()[index] for index in range(3)]
		projection = sum(offset[index] * axis.Direction().Coord()[index] for index in range(3))
		radial = [offset[index] - projection * axis.Direction().Coord()[index] for index in range(3)]
		if sum(normal[index] * radial[index] for index in range(3)) >= 0:
			continue
		bores.append({"face_index": face_index, "diameter": diameter, "axis": axis.Direction().Coord(),
			"origin": axis.Location().Coord(), "u_span": surface.LastUParameter() - surface.FirstUParameter(),
			"v_range": [surface.FirstVParameter(), surface.LastVParameter()]})
	return bores


def completeGroups(bores: list[dict]) -> list[list[dict]]:
	groups = collections.defaultdict(list)
	for bore in bores:
		direction = list(bore["axis"])
		if next(value for value in direction if abs(value) > 1e-7) < 0:
			direction = [-value for value in direction]
		projection = sum(direction[index] * bore["origin"][index] for index in range(3))
		origin = [bore["origin"][index] - projection * direction[index] for index in range(3)]
		groups[tuple(round(value, 6) for value in [bore["diameter"], *direction, *origin])].append(bore)
	complete = []
	for group in groups.values():
		for seed in group:
			direction = seed["axis"]
			section = sum(direction[index] * seed["origin"][index] for index in range(3)) + sum(seed["v_range"]) / 2
			angle = 0.0
			for bore in group:
				projection = sum(direction[index] * bore["origin"][index] for index in range(3))
				sign = sum(direction[index] * bore["axis"][index] for index in range(3))
				lower, upper = sorted(projection + sign * value for value in bore["v_range"])
				if lower + 1e-7 < section < upper - 1e-7:
					angle += bore["u_span"]
			if angle >= 2 * math.pi - 1e-5:
				complete.append(group)
				break
	return complete


def holeKeys(groups: list[list[dict]]) -> list[tuple]:
	keys = []
	for group in groups:
		direction = list(group[0]["axis"])
		if next(value for value in direction if abs(value) > 1e-7) < 0:
			direction = [-value for value in direction]
		projection = sum(direction[index] * group[0]["origin"][index] for index in range(3))
		origin = [group[0]["origin"][index] - projection * direction[index] for index in range(3)]
		ends = []
		for bore in group:
			projection = sum(direction[index] * bore["origin"][index] for index in range(3))
			sign = sum(direction[index] * bore["axis"][index] for index in range(3))
			ends.extend(projection + sign * value for value in bore["v_range"])
		keys.append(tuple(round(value, 6) for value in [group[0]["diameter"], *direction, *origin, min(ends), max(ends)]))
	return sorted(keys)


def boundsKey(shape: cq.Shape) -> tuple:
	bounds = shape.BoundingBox()
	return tuple(round(getattr(bounds, key), 5) for key in ["xmin", "ymin", "zmin", "xmax", "ymax", "zmax"])


class CadModel:
	def __init__(self, path: Path, internal_labels: bool = False) -> None:
		XCAFApp_Application.GetApplication_s()
		self.document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
		self.reader = STEPCAFControl_Reader()
		logger.info("Reading %s", path)
		if self.reader.ReadFile(str(path)) != IFSelect_RetDone or not self.reader.Transfer(self.document):
			raise ValueError(f"Cannot import STEP: {path}")
		self.shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(self.document.Main())
		self.labels = TDF_LabelSequence()
		self.shape_tool.GetShapes(self.labels)
		self.parts = {}
		for index in range(1, self.labels.Length() + 1):
			label = self.labels.Value(index)
			if self.shape_tool.IsSimpleShape_s(label):
				name = self.labelName(label)
				# Mapped prototypes can have identical generic labels. Product/root
				# identities are checked separately; preserve strict names by default.
				if internal_labels:
					name = f"{name} [{index}]"
				if name in self.parts:
					raise ValueError(f"Ambiguous component definition name: {name}")
				self.parts[name] = cq.Shape.cast(self.shape_tool.GetShape_s(label))
		logger.info("Imported %d part definitions", len(self.parts))

	@staticmethod
	def labelName(label: object) -> str:
		# Mapped prototypes may have no name. Avoid FindAttribute's output
		# handle overload: an absent attribute can crash the Python binding.
		attributes = TDF_AttributeIterator(label)
		while attributes.More():
			attribute = attributes.Value()
			if isinstance(attribute, TDataStd_Name):
				return attribute.Get().ToExtString()
			attributes.Next()
		return ""

	def entityShape(self, entity_id: int) -> cq.Shape:
		reader = self.reader.Reader()
		model = reader.StepModel()
		index = model.NextNumberForLabel(f"#{entity_id}")
		if not index:
			raise ValueError(f"Cannot map STEP entity #{entity_id} to the CAD reader")
		shape = reader.WS().TransferReader().ShapeResult(model.Entity(index))
		if shape.IsNull():
			builder = StepToTopoDS_Builder()
			builder.Init(model.Entity(index), reader.WS().TransferReader().TransientProcess())
			if not builder.IsDone():
				raise ValueError(f"Cannot build solid for STEP entity #{entity_id}")
			shape = builder.Value()
		return cq.Shape.cast(shape)

	def inventory(self, diameter: float) -> dict:
		records = {}
		for name, shape in self.parts.items():
			if not shape.isValid() or not shape.Solids():
				raise ValueError(f"Invalid or non-solid component: {name}")
			bores = boreFaces(shape)
			protected = completeGroups([bore for bore in bores if bore["diameter"] >= diameter - DIAMETER_EPSILON_MM])
			records[name] = {"solids": len(shape.Solids()), "faces": len(shape.Faces()), "volume": shape.Volume(),
				"bounds": boundsKey(shape), "protected_holes": holeKeys(protected),
				"small_holes": len(completeGroups(boreFaces(shape, diameter))) if diameter else 0}
		return records

	def instanceNames(self) -> collections.Counter:
		def visit(label: object) -> collections.Counter:
			if self.shape_tool.IsReference_s(label):
				referred = TDF_Label()
				self.shape_tool.GetReferredShape_s(label, referred)
				return visit(referred)
			if self.shape_tool.IsAssembly_s(label):
				children = TDF_LabelSequence()
				self.shape_tool.GetComponents_s(label, children)
				counts = collections.Counter()
				for index in range(1, children.Length() + 1):
					counts.update(visit(children.Value(index)))
				return counts
			return collections.Counter({self.labelName(label): 1})
		roots = TDF_LabelSequence()
		self.shape_tool.GetFreeShapes(roots)
		counts = collections.Counter()
		for index in range(1, roots.Length() + 1):
			counts.update(visit(roots.Value(index)))
		return counts


class HoleRemovalError(ValueError):
	"""Carry rejected geometry until the caller has saved diagnostic evidence."""
	def __init__(self, message: str, original: cq.Shape, candidate: cq.Shape | None, details: dict) -> None:
		super().__init__(message)
		self.original = original
		self.candidate = candidate
		self.details = details


def describeBores(groups: list[list[dict]]) -> list[dict]:
	return [{"key": holeKeys([group])[0], "diameter_mm": group[0]["diameter"],
		"faces": group} for group in groups]


class HoleRemover:
	def __init__(self, diameter: float) -> None:
		self.diameter = diameter

	def flatBoard(self, original: cq.Shape, groups: list[list[dict]]) -> cq.Shape | None:
		faces = original.Faces()
		planes = [face for face in faces if face.geomType() == "PLANE"]
		if len(planes) != 6 or len(original.Solids()) != 1 or any(face.geomType() not in {"PLANE", "CYLINDER"} for face in faces):
			return None
		bounds = original.BoundingBox()
		top = max(planes, key=lambda face: face.Center().z)
		if abs(top.normalAt().z - 1) > 1e-9 or abs(top.Center().z - bounds.zmax) > 1e-7:
			return None
		for face in faces:
			if face.geomType() == "CYLINDER":
				surface = BRepAdaptor_Surface(face.wrapped, True)
				if abs(abs(surface.Cylinder().Axis().Direction().Z()) - 1) > 1e-9 or abs(surface.LastVParameter() - surface.FirstVParameter() - bounds.zlen) > 1e-7:
					return None
		kept = []
		removed = 0
		for wire in top.innerWires():
			edges = wire.Edges()
			if len(edges) != 1 or edges[0].geomType() != "CIRCLE":
				return None
			if edges[0].radius() * 2 < self.diameter - DIAMETER_EPSILON_MM:
				removed += 1
			else:
				kept.append(wire)
		if removed != len(groups):
			return None
		edited = cq.Solid.extrudeLinear(top.outerWire(), kept, (0, 0, -bounds.zlen))
		expected_increase = sum(math.pi * (group[0]["diameter"] / 2) ** 2 * bounds.zlen for group in groups)
		if abs(edited.Volume() - original.Volume() - expected_increase) > 1e-5:
			raise ValueError("Flat-board reconstruction changed more than the selected hole volumes")
		return edited

	def selectedFaces(self, original: cq.Shape, groups: list[list[dict]]) -> set[int]:
		faces = original.Faces()
		selected = {bore["face_index"] for group in groups for bore in group}
		wall_edges = [edge for index in selected for edge in faces[index].Edges()]
		maximum_area = max(math.pi * (group[0]["diameter"] / 2) ** 2 for group in groups)
		for index, face in enumerate(faces):
			if index not in selected and face.geomType() == "PLANE" and face.Area() <= maximum_area + 1e-6:
				edges = face.Edges()
				if edges and all(any(edge.wrapped.IsSame(wall.wrapped) for wall in wall_edges) for edge in edges):
					selected.add(index)
		return selected

	def defeature(self, original: cq.Shape, selected: set[int]) -> tuple[cq.Shape, dict]:
		faces = original.Faces()
		operation = BRepAlgoAPI_Defeaturing()
		operation.SetShape(original.wrapped)
		operation.SetRunParallel(True)
		for index in sorted(selected):
			operation.AddFaceToRemove(faces[index].wrapped)
		operation.Build()
		if not operation.IsDone():
			raise ValueError("Hole defeaturing failed (IsDone=False)")
		# CadQuery's pinned OCP binding does not expose every C++ report method.
		warning_reader = getattr(operation, "HasWarnings", None)
		return cq.Shape.cast(operation.Shape()), {"is_done": True,
			"has_warnings": warning_reader() if warning_reader is not None else None,
			"warning_api_available": warning_reader is not None}

	def checkResult(self, original: cq.Shape, edited: cq.Shape, require_all: bool = True) -> dict:
		checks = {}
		result = {"checks": checks, "check_errors": {}}
		def check(name: str, action: Callable[[], bool]) -> None:
			try:
				checks[name] = action()
			except Exception as error:
				checks[name] = None
				result["check_errors"][name] = str(error)
		def remainingBores() -> bool:
			remaining = completeGroups(boreFaces(edited, self.diameter))
			result["remaining_bores"] = describeBores(remaining)
			return not remaining
		def protected(shape: cq.Shape) -> list[tuple]:
			return holeKeys(completeGroups([bore for bore in boreFaces(shape) if bore["diameter"] >= self.diameter - DIAMETER_EPSILON_MM]))
		def protectedUnchanged() -> bool:
			result["protected_before"] = protected(original)
			result["protected_after"] = protected(edited)
			return result["protected_before"] == result["protected_after"]
		def materialPreserved() -> bool:
			if checks["valid"] is not True:
				raise ValueError("Material comparison not evaluated for invalid or unverified geometry")
			result["removed_volume_mm3"] = original.cut(edited).Volume()
			result["added_volume_mm3"] = edited.Volume() - original.Volume()
			return math.isfinite(result["removed_volume_mm3"]) and result["removed_volume_mm3"] <= 1e-5
		check("valid", edited.isValid)
		check("solid_count_unchanged", lambda: len(edited.Solids()) == len(original.Solids()))
		check("selected_bores_absent", remainingBores)
		check("bounds_unchanged", lambda: boundsKey(original) == boundsKey(edited))
		check("protected_holes_unchanged", protectedUnchanged)
		check("original_material_preserved", materialPreserved)
		result["accepted"] = all(value is True for key, value in checks.items() if require_all or key != "selected_bores_absent")
		return result

	def edit(self, original: cq.Shape) -> tuple[cq.Shape, int]:
		solids = original.Solids()
		if len(solids) > 1:
			# A package's touching/overlapping solids are separate bodies, not a
			# Boolean union. Compound defeaturing can leave a bore untouched.
			edited_solids = []
			count = 0
			for index, solid in enumerate(solids):
				logger.info("Checking solid %d / %d for small holes", index + 1, len(solids))
				edited_solid, removed = self.edit(solid)
				edited_solids.append(edited_solid)
				count += removed
			if not count:
				return original, 0
			edited = cq.Compound.makeCompound(edited_solids)
			details = self.checkResult(original, edited)
			if not details["accepted"]:
				raise HoleRemovalError("Per-solid hole removal failed assembly checks", original, edited, details)
			return edited, count
		groups = completeGroups(boreFaces(original, self.diameter))
		if not groups:
			return original, 0
		edited = None
		details = {"diameter_limit_mm": self.diameter, "selected_bores": describeBores(groups),
			"face_index_basis": "zero-based Faces() on each saved shape; indices are not STEP entity IDs"}
		try:
			selected = self.selectedFaces(original, groups)
			details["selected_face_indices"] = sorted(selected)
			edited = self.flatBoard(original, groups)
			details["method"] = "flat_board" if edited is not None else "defeaturing"
			if edited is None:
				edited, details["operation"] = self.defeature(original, selected)
			details.update(self.checkResult(original, edited))
			if not details["accepted"]:
				failed = [key for key, passed in details["checks"].items() if not passed]
				diameters = [bore["diameter_mm"] for bore in details.get("remaining_bores", [])]
				raise ValueError(f"Hole removal rejected: {failed}; remaining bore diameters mm={diameters}")
		except Exception as error:
			raise HoleRemovalError(str(error), original, edited, details) from error
		return edited, len(groups)
