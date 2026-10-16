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
from .step_graph import SOLID_PREFIXES, StepGraph, references

logger = logging.getLogger(__name__)


def digest(path: Path) -> str:
	return hashlib.sha256(path.read_bytes()).hexdigest()


def checkSharedReferences(original: StepGraph, final: StepGraph, aliases: list[dict], assembly: dict) -> None:
	"""Prove each original solid use survives as a child of its original product."""
	final.checkReferences()
	by_root = {alias["root"]: alias["prototype"] for alias in aliases}
	seen = set()
	prototype_definitions = {}
	affected = set(by_root) | set(by_root.values())
	owners = {entity_id for entity_id, value in original.entities.items()
		if value.startswith(("SHAPE_REPRESENTATION(", "ADVANCED_BREP_SHAPE_REPRESENTATION("))
		and affected.intersection(references(value)[:-1])}
	expected = {(owner, item) for owner in owners for item in references(original.entities[owner])[:-1]
		if original.entities[item].startswith(SOLID_PREFIXES)}
	for record in assembly["occurrences"]:
		root = record["source_root"]
		canonical = by_root.get(root, root)
		owner = record["parent_representation"]
		key = (owner, root)
		if key in seen or key not in expected or record["prototype"] != canonical:
			raise ValueError(f"Incorrect or repeated shared solid use #{root}")
		seen.add(key)
		occurrence = final.entities.get(record["occurrence"], "")
		if not occurrence.startswith("NEXT_ASSEMBLY_USAGE_OCCURRENCE(") or references(occurrence) != [record["parent_definition"], record["prototype_definition"]]:
			raise ValueError(f"Missing shared occurrence for solid #{root}")
		prototype = final.entities[record["prototype_representation"]]
		if not prototype.startswith("ADVANCED_BREP_SHAPE_REPRESENTATION(") or canonical not in references(prototype)[:-1]:
			raise ValueError(f"Incorrect shared prototype for solid #{root}")
		if final.entities.get(canonical) != original.entities[canonical]:
			raise ValueError(f"Shared native solid #{canonical} changed")
		definition = record["prototype_definition"]
		if canonical in prototype_definitions and prototype_definitions[canonical] != definition:
			raise ValueError(f"Solid #{canonical} does not use one shared product definition")
		prototype_definitions[canonical] = definition
		if record["placement"] not in references(final.entities[owner])[:-1]:
			raise ValueError(f"Missing placement for shared solid #{root}")
		transform = final.entities.get(record["transformation"], "")
		if not transform.startswith("ITEM_DEFINED_TRANSFORMATION(") or references(transform)[-1] != record["placement"]:
			raise ValueError(f"Missing transformation for shared solid #{root}")
	if seen != expected:
		raise ValueError("Original solid uses disappeared during assembly instancing")


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
