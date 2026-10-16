"""Share native BReps through ordinary STEP assembly occurrences."""

from .step_graph import SOLID_PREFIXES, StepGraph, references


class AssemblyInstancing:
	def __init__(self, graph: StepGraph) -> None:
		self.graph = graph
		self.next_id = max(graph.entities) + 1
		self.geometry_representations = {}
		for entity_id, value in graph.entities.items():
			if value.startswith(("SHAPE_REPRESENTATION(", "ADVANCED_BREP_SHAPE_REPRESENTATION(")):
				for item in references(value)[:-1]:
					if graph.entities[item].startswith(SOLID_PREFIXES):
						self.geometry_representations[item] = (entity_id, references(value)[-1])
		self.axis_cache = {}
		self.prototype_cache = {}
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

	def prototype(self, root: int, owner: int, context: int) -> tuple[int, int]:
		if root not in self.prototype_cache:
			formation, definition_context = references(self.graph.entities[owner])
			product = references(self.graph.entities[formation])[0]
			product_context = references(self.graph.entities[product])[0]
			name = f"__STEP_SHARED_{root}"
			product = self.add(f"PRODUCT('{name}','{name}','',(#{product_context}))")
			formation = self.add(f"PRODUCT_DEFINITION_FORMATION('','',#{product})")
			definition = self.add(f"PRODUCT_DEFINITION('design','',#{formation},#{definition_context})")
			definition_shape = self.add(f"PRODUCT_DEFINITION_SHAPE('','',#{definition})")
			representation = self.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('',(#{self.identity},#{root}),#{context})")
			self.add(f"SHAPE_DEFINITION_REPRESENTATION(#{definition_shape},#{representation})")
			self.add(f"PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,(#{product}))")
			self.prototype_cache[root] = (definition, representation)
		return self.prototype_cache[root]

	def apply(self, aliases: list[dict]) -> dict:
		"""Convert affected packages into assemblies; retain each solid as a child."""
		by_root = {alias["root"]: alias for alias in aliases}
		affected = set(by_root) | {alias["prototype"] for alias in aliases}
		owners = {}
		for value in list(self.graph.entities.values()):
			if value.startswith("SHAPE_DEFINITION_REPRESENTATION("):
				definition_shape, representation = references(value)
				owners[representation] = references(self.graph.entities[definition_shape])[-1]
		proofs = []
		for representation, owner in owners.items():
			value = self.graph.entities[representation]
			items = references(value)[:-1]
			roots = [item for item in items if self.graph.entities[item].startswith(SOLID_PREFIXES)]
			if not affected.intersection(roots):
				continue
			context = references(value)[-1]
			placements = [item for item in items if item not in roots]
			for root in roots:
				alias = by_root.get(root)
				canonical = alias["prototype"] if alias else root
				child, child_representation = self.prototype(canonical, owner, context)
				placement = self.axis(alias["translation"], alias["rotation"]) if alias else self.identity
				placements.append(placement)
				occurrence = self.add(f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('shared_{root}','solid_{root}','',#{owner},#{child},$)")
				definition_shape = self.add(f"PRODUCT_DEFINITION_SHAPE('Placement','Placement of shared solid',#{occurrence})")
				transform = self.add(f"ITEM_DEFINED_TRANSFORMATION('','',#{self.identity},#{placement})")
				relationship = self.add(f"( REPRESENTATION_RELATIONSHIP('','',#{child_representation},#{representation}) REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#{transform}) SHAPE_REPRESENTATION_RELATIONSHIP() )")
				self.add(f"CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#{relationship},#{definition_shape})")
				proofs.append({"source_root": root, "prototype": canonical, "parent_definition": owner,
					"parent_representation": representation, "prototype_definition": child,
					"prototype_representation": child_representation, "occurrence": occurrence,
					"transformation": transform, "placement": placement})
			# Assemblies contain placements; their BReps are in child products.
			# MAPPED_ITEM inside a multi-body part is ignored by SolidWorks 2025.
			item_text = ",".join(f"#{item}" for item in dict.fromkeys(placements))
			self.graph.entities[representation] = f"SHAPE_REPRESENTATION('',({item_text}),#{context})"
		return {"occurrences": proofs, "prototypes": len(self.prototype_cache)}
