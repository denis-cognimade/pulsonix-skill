"""Find conservative solid/appearance matches under translation and 24 proper rotations."""

import collections
import hashlib
import itertools
import logging
import re

from .step_graph import StepGraph, TOKEN_PATTERN, references

logger = logging.getLogger(__name__)


def rotations() -> list[tuple]:
	result = []
	for permutation in itertools.permutations(range(3)):
		parity = (-1) ** sum(permutation[left] > permutation[right] for left in range(3) for right in range(left + 1, 3))
		for signs in itertools.product([-1, 1], repeat=3):
			if parity * signs[0] * signs[1] * signs[2] == 1:
				result.append(tuple(tuple(signs[row] if column == permutation[row] else 0 for column in range(3)) for row in range(3)))
	return result


def multiply(matrix: tuple | list, vector: tuple | list) -> list[float]:
	return [sum(matrix[row][column] * vector[column] for column in range(3)) for row in range(3)]


class InstancingPlanner:
	def __init__(self, graph: StepGraph) -> None:
		self.graph = graph
		self.points = {}
		for entity_id, value in self.graph.entities.items():
			if value.startswith(("CARTESIAN_POINT(", "DIRECTION(")):
				match = re.fullmatch(r"(CARTESIAN_POINT|DIRECTION)\('(?:[^']|'')*',\s*\(([^)]+)\)\)", value)
				if match:
					coordinates = tuple(float(number) for number in match.group(2).split(","))
					if len(coordinates) == 3:
						self.points[entity_id] = (match.group(1), coordinates)
		self.styles = collections.defaultdict(list)
		for entity_id, value in self.graph.entities.items():
			if value.startswith("STYLED_ITEM("):
				self.styles[references(value)[-1]].append(entity_id)
			elif value.startswith("OVER_RIDING_STYLED_ITEM("):
				self.styles[references(value)[-2]].append(entity_id)

	def anchor(self, root: int) -> tuple:
		pending = [root]
		visited = set()
		while pending:
			entity_id = pending.pop()
			if entity_id in visited:
				continue
			visited.add(entity_id)
			if entity_id in self.points and self.points[entity_id][0] == "CARTESIAN_POINT":
				return self.points[entity_id][1]
			pending.extend(reversed(references(self.graph.entities[entity_id])))
		raise ValueError(f"No coordinate anchor in solid #{root}")

	def fingerprint(self, root: int, anchor: tuple, rotation: tuple, style_ids: list[int]) -> tuple:
		cache = {}
		active = set()
		def visit(entity_id: int) -> str:
			if entity_id in cache:
				return cache[entity_id]
			if entity_id in active:
				raise ValueError(f"Contextual or cyclic style on solid #{root}")
			active.add(entity_id)
			if entity_id in self.points:
				kind, values = self.points[entity_id]
				if kind == "CARTESIAN_POINT":
					values = [values[index] - anchor[index] for index in range(3)]
				values = multiply(rotation, values)
				value = f"{kind}({','.join(str(round(value, 8) + 0.0) for value in values)})"
			else:
				value = TOKEN_PATTERN.sub(lambda match: f"@{visit(int(match.group(1)))}" if match.group(1) else match.group(0), self.graph.entities[entity_id])
				value = re.sub(r"\s+", "", value)
			digest = hashlib.sha256(value.encode()).hexdigest()
			cache[entity_id] = digest
			active.remove(entity_id)
			return digest
		geometry = visit(root)
		appearance = hashlib.sha256("".join(sorted(visit(style_id) for style_id in style_ids)).encode()).hexdigest()
		return geometry, appearance

	def plan(self) -> dict:
		products = self.graph.productSolids()
		records = []
		variants = rotations()
		for name, roots in products.items():
			for root in roots:
				anchor = self.anchor(root)
				closure = self.graph.closure({root})
				style_ids = [style_id for entity_id in closure for style_id in self.styles.get(entity_id, [])]
				candidates = []
				for rotation in variants:
					geometry, appearance = self.fingerprint(root, anchor, rotation, style_ids)
					candidates.append((geometry, appearance, rotation))
				geometry, appearance, rotation = min(candidates)
				records.append({"name": name, "root": root, "anchor": anchor, "rotation": rotation,
					"geometry": geometry, "appearance": appearance, "records": len(closure)})
				if len(records) % 25 == 0:
					logger.info("Analyzed %d / %d solid definitions", len(records), sum(map(len, products.values())))
		groups = collections.defaultdict(list)
		for record in records:
			groups[(record["geometry"], record["appearance"])].append(record)
		duplicates = [group for group in groups.values() if len(group) > 1]
		geometry_groups = collections.defaultdict(list)
		for record in records:
			geometry_groups[record["geometry"]].append(record)
		report = {"solid_definitions": len(records), "prototype_count": len(groups),
			"geometry_prototype_count": len(geometry_groups), "shared_groups": duplicates,
			"all_solids": records}
		logger.info("%d solids -> %d geometry/appearance prototypes (%d geometry-only prototypes)", len(records), len(groups), len(geometry_groups))
		logger.info("%d reusable groups; %d duplicate solid definitions", len(duplicates), sum(len(group) - 1 for group in duplicates))
		return report
