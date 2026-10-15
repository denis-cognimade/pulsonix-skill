"""Share native BRep definitions using STEP representation maps."""

from .step_graph import StepGraph, references


class MappedInstancing:
	def __init__(self, graph: StepGraph) -> None:
		self.graph = graph
		self.next_id = max(graph.entities) + 1
		self.geometry_representations = {}
		for entity_id, value in graph.entities.items():
			if value.startswith(("SHAPE_REPRESENTATION(", "ADVANCED_BREP_SHAPE_REPRESENTATION(")):
				for item in references(value)[:-1]:
					if graph.entities[item].startswith("MANIFOLD_SOLID_BREP("):
						self.geometry_representations[item] = (entity_id, references(value)[-1])
		self.axis_cache = {}
		self.map_cache = {}
		self.identity = self.axis((0, 0, 0), ((1, 0, 0), (0, 1, 0), (0, 0, 1)))

	def add(self, value: str) -> int:
		entity_id = self.next_id
		self.next_id += 1
		self.graph.entities[entity_id] = value
		return entity_id

	def axis(self, origin: tuple | list, rotation: tuple | list) -> int:
		key = tuple(round(value, 10) for value in origin) + tuple(value for row in rotation for value in row)
		if key not in self.axis_cache:
			position = self.add(f"CARTESIAN_POINT('',({','.join(f'{value:.12g}' for value in origin)}))")
			axis_z = self.add(f"DIRECTION('',({','.join(str(rotation[row][2]) for row in range(3))}))")
			axis_x = self.add(f"DIRECTION('',({','.join(str(rotation[row][0]) for row in range(3))}))")
			self.axis_cache[key] = self.add(f"AXIS2_PLACEMENT_3D('',#{position},#{axis_z},#{axis_x})")
		return self.axis_cache[key]

	def prototype(self, root: int) -> int:
		if root not in self.map_cache:
			_, context = self.geometry_representations[root]
			representation = self.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('',(#{self.identity},#{root}),#{context})")
			self.map_cache[root] = self.add(f"REPRESENTATION_MAP(#{self.identity},#{representation})")
		return self.map_cache[root]

	def instance(self, duplicate: int, canonical: int, rotation: list | tuple, translation: list | tuple) -> None:
		representation_map = self.prototype(canonical)
		placement = self.axis(translation, rotation)
		self.graph.entities[duplicate] = f"MAPPED_ITEM('',#{representation_map},#{placement})"
		representation, _ = self.geometry_representations[duplicate]
		value = self.graph.entities[representation]
		if value.startswith("ADVANCED_BREP_SHAPE_REPRESENTATION("):
			self.graph.entities[representation] = value.replace("ADVANCED_BREP_SHAPE_REPRESENTATION(", "SHAPE_REPRESENTATION(", 1)
