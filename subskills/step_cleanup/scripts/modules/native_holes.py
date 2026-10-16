"""Close proven cylindrical bores by editing native shell and face boundaries."""

import math
import re
from pathlib import Path

from .cad_geometry import CadModel, boreFaces, completeGroups, holeKeys
from .instancing_plan import InstancingPlanner
from .step_graph import StepGraph, references


class NativeHoleEditor:
	def __init__(self, graph: StepGraph) -> None:
		self.graph = graph
		self.points = InstancingPlanner(graph).points

	def edgeSet(self, bound: int) -> set[int]:
		loop = references(self.graph.entities[bound])[0]
		if not self.graph.entities[loop].startswith("EDGE_LOOP("):
			raise ValueError("Native bore requires an edge loop")
		return {references(self.graph.entities[item])[-1] for item in references(self.graph.entities[loop])}

	def cylinderKey(self, surface: int) -> tuple | None:
		value = self.graph.entities[surface]
		if not value.startswith("CYLINDRICAL_SURFACE("):
			return None
		radius = float(value.rsplit(",", 1)[1][:-1])
		placement = references(value)[0]
		position, axis, *_ = references(self.graph.entities[placement])
		origin = self.points[position][1]
		direction = self.points[axis][1]
		length = math.sqrt(sum(component ** 2 for component in direction))
		direction = tuple(component / length for component in direction)
		if next(component for component in direction if abs(component) > 1e-7) < 0:
			direction = tuple(-component for component in direction)
		projection = sum(direction[index] * origin[index] for index in range(3))
		line = [origin[index] - projection * direction[index] for index in range(3)]
		return tuple(round(component, 6) for component in (2 * radius, *direction, *line))

	def withoutItems(self, value: str, removed: set[int]) -> str:
		# These supported records have one first aggregate of entity references.
		pattern = re.compile(r"\((\s*#\d+(?:\s*,\s*#\d+)*\s*)\)")
		match = pattern.search(value)
		if match is None:
			raise ValueError("Unrecognized native face/shell aggregate")
		kept = [item for item in references(match.group(1)) if item not in removed]
		if not kept:
			raise ValueError("Native hole edit would empty a face or shell")
		return f"{value[:match.start(1)]}{','.join(f'#{item}' for item in kept)}{value[match.end(1):]}"

	def plan(self, roots: list[int], groups: list[list[dict]]) -> dict:
		closure = self.graph.closure(set(roots))
		faces = {entity_id for entity_id in closure if self.graph.entities[entity_id].startswith("ADVANCED_FACE(")}
		face_bounds = {face: references(self.graph.entities[face])[:-1] for face in faces}
		bound_edges = {bound: self.edgeSet(bound) for bounds in face_bounds.values() for bound in bounds}
		removed_faces = set()
		removed_bounds = {}
		area_delta = 0.0
		filled_volume = 0.0
		for group in groups:
			key = holeKeys([group])[0]
			walls = {face for face in faces if self.cylinderKey(references(self.graph.entities[face])[-1]) == key[:7]}
			if len(walls) != len(group):
				raise ValueError("Ambiguous native cylinder wall correspondence")
			wall_edges = {edge for face in walls for bound in face_bounds[face] for edge in bound_edges[bound]}
			# Prove both axial ends match this complete bore, not a coaxial recess.
			vertices = {vertex for edge in wall_edges for vertex in references(self.graph.entities[edge])[:2]}
			positions = [self.points[references(self.graph.entities[vertex])[0]][1] for vertex in vertices]
			depths = [sum(key[index + 1] * position[index] for index in range(3)) for position in positions]
			if not depths or abs(min(depths) - key[-2]) > 1e-6 or abs(max(depths) - key[-1]) > 1e-6:
				raise ValueError("Native cylinder axial range does not match the selected bore")
			mouths = []
			floors = []
			for face in faces - walls:
				matched = [bound for bound in face_bounds[face] if bound_edges[bound] and bound_edges[bound] <= wall_edges]
				if not matched:
					continue
				surface = references(self.graph.entities[face])[-1]
				if not self.graph.entities[surface].startswith("PLANE("):
					raise ValueError("Native cylinder closure requires planar caps/openings")
				placement = references(self.graph.entities[surface])[0]
				position, axis, *_ = references(self.graph.entities[placement])
				normal = self.points[axis][1]
				if abs(abs(sum(normal[index] * key[index + 1] for index in range(3))) - 1) > 1e-7:
					raise ValueError("Native cylinder cap plane is not perpendicular to its axis")
				depth = sum(self.points[position][1][index] * key[index + 1] for index in range(3))
				if min(abs(depth - key[-2]), abs(depth - key[-1])) > 1e-6:
					raise ValueError("Native cap does not lie at an end of the bore")
				if matched == face_bounds[face]:
					if len(matched) != 1:
						raise ValueError("Native floor has an unsupported boundary")
					floors.append(face)
				else:
					if len(matched) != 1 or not self.graph.entities[matched[0]].startswith("FACE_BOUND("):
						raise ValueError("Native bore mouth must be an inner face boundary")
					mouths.append((face, matched[0]))
			if (len(mouths), len(floors)) not in {(1, 1), (2, 0)}:
				raise ValueError("Native bore is not an isolated blind or through cylinder")
			# Every cap is exactly the selected circular rim; no adjoining recess.
			for face in floors + [face for face, _ in mouths]:
				for bound in face_bounds[face]:
					if not bound_edges[bound] <= wall_edges:
						continue
					for edge in bound_edges[bound]:
						curve = references(self.graph.entities[edge])[-1]
						curve_value = self.graph.entities[curve]
						if curve_value.startswith(("SURFACE_CURVE(", "SEAM_CURVE(")):
							curve_value = self.graph.entities[references(curve_value)[0]]
						if not curve_value.startswith("CIRCLE(") or abs(2 * float(curve_value.rsplit(",", 1)[1][:-1]) - key[0]) > 1e-6:
							raise ValueError("Native cap rim is not the selected circle")
			removed_faces.update(walls | set(floors))
			for face, bound in mouths:
				removed_bounds.setdefault(face, set()).add(bound)
			radius = group[0]["diameter"] / 2
			depth = key[-1] - key[-2]
			area_delta += (len(mouths) - len(floors)) * math.pi * radius ** 2 - 2 * math.pi * radius * depth
			filled_volume += math.pi * radius ** 2 * depth
		changes = {face: self.withoutItems(self.graph.entities[face], bounds) for face, bounds in removed_bounds.items()}
		for entity_id in closure:
			value = self.graph.entities[entity_id]
			if value.startswith("CLOSED_SHELL(") and removed_faces.intersection(references(value)):
				changes[entity_id] = self.withoutItems(value, removed_faces)
		return {"changes": changes, "removed_face_ids": sorted(removed_faces),
			"removed_bound_ids": sorted(bound for bounds in removed_bounds.values() for bound in bounds),
			"area_delta_mm2": area_delta, "cavity_volume_mm3": filled_volume, "bores": len(groups)}


def repairNativeHoles(graph: StepGraph, model: CadModel, name: str, diameter: float, work: Path) -> tuple[object, dict]:
	"""Use native boundary proofs when the general CAD operation leaves a bore."""
	original = model.parts[name]
	groups = completeGroups(boreFaces(original, diameter))
	plan = NativeHoleEditor(graph).plan(graph.productSolids()[name], groups)
	before = dict(graph.entities)
	try:
		graph.entities.update(plan["changes"])
		path = work / "native_hole_candidate.stp"
		graph.write(path)
		candidate_model = CadModel(path)
		candidate = candidate_model.parts[name]
		baseline = model.inventory(diameter)[name]
		actual = candidate_model.inventory(diameter)[name]
		for key in ("solids", "bounds", "protected_holes"):
			if baseline[key] != actual[key]:
				raise ValueError(f"Native bore repair changed {name}: {key}")
		if actual["small_holes"] or actual["faces"] != baseline["faces"] - len(plan["removed_face_ids"]):
			raise ValueError("Native bore repair left holes or changed unrelated faces")
		if abs(candidate.Area() - original.Area() - plan["area_delta_mm2"]) > 1e-5:
			raise ValueError("Native bore repair changed area outside the selected cavities")
		# Only shell membership and proven planar mouth trims were changed.
		# This proves material preservation locally without unreliable compound
		# Booleans or re-exporting unrelated curves, surfaces, and appearances.
		proof = {key: value for key, value in plan.items() if key != "changes"}
		proof.update({"method": "native_planar_cylinders", "changed_records": [
			{"id": entity_id, "before": before[entity_id], "after": value} for entity_id, value in plan["changes"].items()],
			"native_boundary_proof_passed": True, "area_check_passed": True,
			"kernel_volume_delta_mm3": candidate.Volume() - original.Volume()})
		return candidate, proof
	except Exception:
		graph.entities = before
		raise
