"""Preserve STEP records while pruning supported Pulsonix/Open CASCADE exports."""

import collections
import re
from pathlib import Path

ENTITY_PATTERN = re.compile(r"#(\d+)\s*=\s*((?:'(?:[^']|'')*'|[^;'])*);", re.DOTALL)
TOKEN_PATTERN = re.compile(r"'(?:[^']|'')*'|#(\d+)")
PRESENTATION_TYPE = "MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION"
# Unknown record families may carry semantic roots and must not silently disappear.
KNOWN_TYPES = set("""APPLICATION_PROTOCOL_DEFINITION APPLICATION_CONTEXT
SHAPE_DEFINITION_REPRESENTATION PRODUCT_DEFINITION_SHAPE PRODUCT_DEFINITION
PRODUCT_DEFINITION_FORMATION PRODUCT PRODUCT_CONTEXT PRODUCT_DEFINITION_CONTEXT
SHAPE_REPRESENTATION ADVANCED_BREP_SHAPE_REPRESENTATION PRODUCT_RELATED_PRODUCT_CATEGORY
CONTEXT_DEPENDENT_SHAPE_REPRESENTATION ITEM_DEFINED_TRANSFORMATION NEXT_ASSEMBLY_USAGE_OCCURRENCE
AXIS2_PLACEMENT_3D AXIS2_PLACEMENT_2D AXIS1_PLACEMENT CARTESIAN_POINT DIRECTION
UNCERTAINTY_MEASURE_WITH_UNIT MANIFOLD_SOLID_BREP CLOSED_SHELL ADVANCED_FACE FACE_BOUND
FACE_OUTER_BOUND EDGE_LOOP ORIENTED_EDGE EDGE_CURVE VERTEX_POINT LINE VECTOR PLANE
ELLIPSE CYLINDRICAL_SURFACE CIRCLE SPHERICAL_SURFACE B_SPLINE_CURVE_WITH_KNOTS
CONICAL_SURFACE TOROIDAL_SURFACE B_SPLINE_SURFACE_WITH_KNOTS SURFACE_OF_REVOLUTION
MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION STYLED_ITEM
PRESENTATION_STYLE_ASSIGNMENT SURFACE_STYLE_USAGE SURFACE_SIDE_STYLE SURFACE_STYLE_FILL_AREA
FILL_AREA_STYLE FILL_AREA_STYLE_COLOUR COLOUR_RGB CURVE_STYLE DRAUGHTING_PRE_DEFINED_CURVE_FONT
OVER_RIDING_STYLED_ITEM DRAUGHTING_PRE_DEFINED_COLOUR PRESENTATION_STYLE_BY_CONTEXT
SURFACE_CURVE PCURVE DEFINITIONAL_REPRESENTATION SEAM_CURVE
REPRESENTATION_MAP MAPPED_ITEM CARTESIAN_TRANSFORMATION_OPERATOR_3D""".split())


def references(value: str) -> list[int]:
	return [int(match.group(1)) for match in TOKEN_PATTERN.finditer(value) if match.group(1)]


def remapReferences(value: str, mapping: dict[int, int]) -> str:
	return TOKEN_PATTERN.sub(lambda match: f"#{mapping[int(match.group(1))]}" if match.group(1) else match.group(0), value)


class StepGraph:
	def __init__(self, path: Path) -> None:
		self.text = path.read_text(encoding="utf-8")
		if "/*" in self.text or self.text.count("\nDATA;") != 1:
			raise ValueError("Helper supports one DATA section without STEP comments; use a format-aware adapter for this file")
		matches = list(ENTITY_PATTERN.finditer(self.text))
		self.entities = {int(match.group(1)): match.group(2) for match in matches}
		if not matches or len(matches) != len(self.entities):
			raise ValueError("No STEP entities or duplicate entity IDs")
		self.original_entities = dict(self.entities)
		for value in self.entities.values():
			if "LENGTH_UNIT()" in value and "SI_UNIT(.MILLI.,.METRE.)" not in re.sub(r"\s+", "", value):
				raise ValueError("Helper supports millimetre STEP contexts; convert other units explicitly before transplanting geometry")
		self.checkReferences()

	def checkReferences(self) -> None:
		for entity_id, value in self.entities.items():
			missing = {reference for reference in references(value) if reference not in self.entities}
			if missing:
				raise ValueError(f"Dangling references in #{entity_id}: {sorted(missing)}")

	def closure(self, roots: set[int]) -> set[int]:
		visited = set()
		pending = list(roots)
		while pending:
			entity_id = pending.pop()
			if entity_id not in visited:
				visited.add(entity_id)
				pending.extend(references(self.entities[entity_id]))
		return visited

	def definitions(self) -> tuple[dict[int, str], dict[int, int]]:
		products = {}
		for entity_id, value in self.entities.items():
			if value.startswith("PRODUCT("):
				match = re.match(r"PRODUCT\('((?:[^']|'')*)'", value)
				if match is None:
					raise ValueError(f"Unrecognized product name in #{entity_id}")
				products[entity_id] = match.group(1).replace("''", "'")
		names = {}
		product_ids = {}
		for entity_id, value in self.entities.items():
			if value.startswith("PRODUCT_DEFINITION("):
				formation = references(value)[0]
				product = references(self.entities[formation])[0]
				names[entity_id] = products[product]
				product_ids[entity_id] = product
		return names, product_ids

	def productSolids(self) -> dict[str, list[int]]:
		names, _ = self.definitions()
		products = {}
		for value in self.entities.values():
			if not value.startswith("SHAPE_DEFINITION_REPRESENTATION("):
				continue
			definition_shape, representation = references(value)
			definition = references(self.entities[definition_shape])[-1]
			solids = [item for item in references(self.entities[representation]) if self.entities[item].startswith("MANIFOLD_SOLID_BREP(")]
			if solids:
				name = names[definition]
				if name in products:
					raise ValueError(f"Ambiguous solid product name: {name}")
				products[name] = solids
		return products

	def write(self, path: Path) -> None:
		self.checkReferences()
		def renderEntity(match: re.Match) -> str:
			entity_id = int(match.group(1))
			if entity_id not in self.entities:
				return ""
			value = self.entities[entity_id]
			return match.group(0) if value == self.original_entities[entity_id] else f"#{entity_id} = {value};"
		result = ENTITY_PATTERN.sub(renderEntity, self.text)
		added = "\n".join(f"#{entity_id} = {value};" for entity_id, value in self.entities.items() if entity_id not in self.original_entities)
		position = result.rfind("ENDSEC;")
		result = f"{result[:position]}{added}\n{result[position:]}"
		result = "\n".join(line for line in result.splitlines() if line.strip())
		path.write_text(f"{result}\n", encoding="utf-8", newline="\n")
		check = StepGraph(path)
		if check.entities != self.entities:
			raise ValueError("STEP serialization changed a retained record")

	def transplant(self, donor: "StepGraph", root_mapping: dict[int, int]) -> None:
		closure = donor.closure(set(root_mapping))
		mapping = dict(root_mapping)
		next_id = max(self.entities) + 1
		for entity_id in sorted(closure):
			if entity_id not in mapping:
				mapping[entity_id] = next_id
				next_id += 1
		for entity_id in sorted(closure):
			self.entities[mapping[entity_id]] = remapReferences(donor.entities[entity_id], mapping)

	def prune(self, prefixes: tuple[str, ...]) -> dict:
		unknown = {value.split("(", 1)[0].strip() for value in self.entities.values()} - KNOWN_TYPES - {""}
		if unknown:
			raise ValueError(f"Unsupported STEP record families; inspect semantic roots before editing: {sorted(unknown)}")
		names, product_ids = self.definitions()
		targets = {entity_id for entity_id, name in names.items() if prefixes and name.startswith(prefixes)}
		occurrences = {entity_id: references(value) for entity_id, value in self.entities.items() if value.startswith("NEXT_ASSEMBLY_USAGE_OCCURRENCE(")}
		if any(len(pair) != 2 for pair in occurrences.values()):
			raise ValueError("Unsupported assembly occurrence layout")
		removed_occurrences = {entity_id for entity_id, (_, child) in occurrences.items() if child in targets}
		wrappers = {parent for entity_id, (parent, _) in occurrences.items() if entity_id in removed_occurrences}
		if any(child not in targets for parent, child in occurrences.values() if parent in wrappers):
			raise ValueError("Mixed parent assembly: helper requires independent placement wrappers for named component removal")
		removed_definitions = targets | wrappers
		removed_products = {product_ids[entity_id] for entity_id in removed_definitions}
		roots = set()
		for entity_id, value in self.entities.items():
			if value.startswith("APPLICATION_PROTOCOL_DEFINITION("):
				roots.add(entity_id)
			elif value.startswith("SHAPE_DEFINITION_REPRESENTATION("):
				definition_shape = references(value)[0]
				owner = references(self.entities[definition_shape])[-1]
				if owner not in removed_definitions | removed_occurrences:
					roots.add(entity_id)
			elif value.startswith("CONTEXT_DEPENDENT_SHAPE_REPRESENTATION("):
				definition_shape = references(value)[-1]
				if references(self.entities[definition_shape])[-1] not in removed_occurrences:
					roots.add(entity_id)
			elif value.startswith("PRODUCT_RELATED_PRODUCT_CATEGORY("):
				products = references(value)
				if set(products) & removed_products:
					if not set(products) <= removed_products:
						raise ValueError("Mixed product category requires an explicit adapter")
				else:
					roots.add(entity_id)
		geometry = self.closure(roots)
		styles = set()
		for entity_id, value in self.entities.items():
			if value.startswith("STYLED_ITEM(") and references(value)[-1] in geometry:
				styles.add(entity_id)
			elif value.startswith("OVER_RIDING_STYLED_ITEM(") and references(value)[-2] in geometry:
				styles.add(entity_id)
		pattern = re.compile(rf"({PRESENTATION_TYPE}\('[^']*',\s*\()(.*)(\),\s*#\d+\))", re.DOTALL)
		for entity_id, value in list(self.entities.items()):
			if value.startswith(f"{PRESENTATION_TYPE}("):
				items = references(value)[:-1]
				kept = [item for item in items if item in styles]
				if kept:
					roots.add(entity_id)
					if kept != items:
						match = pattern.fullmatch(value)
						if match is None:
							raise ValueError(f"Unsupported presentation record #{entity_id}")
						item_text = ",".join(f"#{item}" for item in kept)
						self.entities[entity_id] = f"{match.group(1)}{item_text}{match.group(3)}"
		retained = self.closure(roots | styles)
		if retained & (removed_definitions | removed_products | removed_occurrences):
			raise ValueError("Removed product remains reachable through unsupported assembly or style metadata")
		if set(occurrences) & retained != set(occurrences) - removed_occurrences:
			raise ValueError("Pruning would change an unselected assembly occurrence")
		removed_records = len(self.entities) - len(retained)
		self.entities = {entity_id: value for entity_id, value in self.entities.items() if entity_id in retained}
		self.checkReferences()
		return {"removed_definitions": sorted(names[entity_id] for entity_id in targets),
			"removed_instances": dict(collections.Counter(next(prefix for prefix in prefixes if names[occurrences[entity_id][1]].startswith(prefix)) for entity_id in removed_occurrences)),
			"discarded_records": removed_records,
			"remaining_instances_by_name": dict(collections.Counter(names[child] for entity_id, (_, child) in occurrences.items() if entity_id in retained))}
