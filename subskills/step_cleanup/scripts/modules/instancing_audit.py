"""Validate rigid matches, world geometry, inherited appearance, and actual sharing."""

import hashlib
import logging
from pathlib import Path

import cadquery as cq
from OCP.TDF import TDF_LabelSequence
from OCP.Quantity import Quantity_TOC_RGB
from OCP.TopLoc import TopLoc_Location
from OCP.XCAFPrs import XCAFPrs, XCAFPrs_IndexedDataMapOfShapeStyle
from OCP.gp import gp_Trsf

from .cad_geometry import CadModel, boundsKey
from .instancing_plan import multiply

logger = logging.getLogger(__name__)


def digest(path: Path) -> str:
	return hashlib.sha256(path.read_bytes()).hexdigest()


def rigidTransform(canonical: dict, duplicate: dict) -> tuple[list, list]:
	left = duplicate["rotation"]
	right = canonical["rotation"]
	rotation = [[sum(left[index][row] * right[index][column] for index in range(3)) for column in range(3)] for row in range(3)]
	rotated = multiply(rotation, canonical["anchor"])
	translation = [duplicate["anchor"][index] - rotated[index] for index in range(3)]
	return rotation, translation


def cadTransform(rotation: list, translation: list) -> cq.Location:
	matrix = gp_Trsf()
	matrix.SetValues(*[value for row in range(3) for value in [*rotation[row], translation[row]]])
	return cq.Location(matrix)


def uniqueGeometry(shapes: list) -> int:
	representatives = []
	for shape in shapes:
		if not any(shape.wrapped.IsPartner(other.wrapped) for other in representatives):
			representatives.append(shape)
	return len(representatives)


def worldInventory(model: CadModel) -> dict:
	roots = TDF_LabelSequence()
	model.shape_tool.GetFreeShapes(roots)
	result = {}
	for index in range(1, roots.Length() + 1):
		label = roots.Value(index)
		name = model.labelName(label)
		if name in result:
			raise ValueError(f"Ambiguous root instance name {name}")
		shape = cq.Shape.cast(model.shape_tool.GetShape_s(label))
		if not shape.isValid():
			raise ValueError(f"Invalid instance {name}")
		settings = XCAFPrs_IndexedDataMapOfShapeStyle()
		XCAFPrs.CollectStyleSettings_s(label, TopLoc_Location(), settings)
		appearance = []
		def visit(current: cq.Shape, inherited: tuple) -> None:
			surface, curve, visible = inherited
			if settings.Contains(current.wrapped):
				style = settings.FindFromKey(current.wrapped)
				if style.IsSetColorSurf():
					color = style.GetColorSurfRGBA()
					surface = tuple(round(value, 6) for value in (*color.GetRGB().Values(Quantity_TOC_RGB), color.Alpha()))
				if style.IsSetColorCurv():
					curve = tuple(round(value, 6) for value in style.GetColorCurv().Values(Quantity_TOC_RGB))
				visible = visible and style.IsVisible()
			if isinstance(current, cq.Face):
				appearance.append((boundsKey(current), round(current.Area(), 5), surface, curve, visible))
			else:
				for child in current:
					visit(child, (surface, curve, visible))
		visit(shape, (None, None, True))
		result[name] = {"bounds": boundsKey(shape), "volume": shape.Volume(), "area": shape.Area(),
			"solids": len(shape.Solids()), "faces": len(shape.Faces()),
			"center": shape.Center().toTuple(), "appearance": sorted(appearance, key=repr)}
		if index % 30 == 0:
			logger.info("Audited %d / %d placed components", index, roots.Length())
	return result


def worldSolids(model: CadModel) -> list[cq.Shape]:
	roots = TDF_LabelSequence()
	model.shape_tool.GetFreeShapes(roots)
	return [solid for index in range(1, roots.Length() + 1)
		for solid in cq.Shape.cast(model.shape_tool.GetShape_s(roots.Value(index))).Solids()]


def compareInventories(before: dict, after: dict) -> None:
	if before.keys() != after.keys():
		raise ValueError("Named assembly roots changed during instancing")
	for name, record in before.items():
		other = after[name]
		for key in ["bounds", "solids", "faces", "appearance"]:
			if record[key] != other[key]:
				raise ValueError(f"Instance {name} changed {key}")
		if abs(record["volume"] - other["volume"]) > 1e-5 or abs(record["area"] - other["area"]) > 1e-4:
			raise ValueError(f"Instance {name} changed volume or area")
		if any(abs(first - second) > 1e-6 for first, second in zip(record["center"], other["center"])):
			raise ValueError(f"Instance {name} moved its center of mass")
