"""Locate an optional generated Pulsonix Python client in bounded directories."""

import argparse
import os
from pathlib import Path
import sys

from modules.runtime import RuntimeSupport


PACKAGE_MARKERS = (
	Path("pulsonix") / "__init__.py",
	Path("pulsonix") / "psxutils.py",
)
DEFAULT_DEVELOPMENT_ROOT = Path(r"C:\Development\PulsonixMcp")


class PulsonixClientFinder:
	"""Find the directory that can be added to Python's import path."""

	_instance: "PulsonixClientFinder | None" = None

	def __init__(self) -> None:
		self.runtime = RuntimeSupport.getInstance()
		self.logger = self.runtime.configureLogging("pulsonix.find_client")

	@classmethod
	def getInstance(cls) -> "PulsonixClientFinder":
		if cls._instance is None:
			cls._instance = cls()
		return cls._instance

	def run(self, arguments: argparse.Namespace) -> int:
		try:
			if arguments.max_depth < 0:
				raise ValueError("--max-depth cannot be negative")
			roots = self._candidateRoots(arguments.root)
			if not roots:
				raise FileNotFoundError("No requested client search root exists")
			matches = self._findClients(roots, arguments.max_depth)
			if not matches:
				searched_roots = ", ".join(str(root) for root in roots)
				raise FileNotFoundError(
					"No generated Pulsonix client was found under the bounded roots: "
					f"{searched_roots}"
				)
			for match in matches:
				self.logger.info(str(match))
			return 0
		except Exception as error:
			self.logger.error(f"Pulsonix client search failed because {error}")
			return 1

	def _candidateRoots(self, requested_roots: list[str]) -> list[Path]:
		candidate_roots: list[Path] = []
		environment_path = os.environ.get("PULSONIX_CLIENT_PATH", "").strip()
		if environment_path:
			candidate_roots.append(Path(environment_path))
		candidate_roots.extend(Path(root) for root in requested_roots)
		if not requested_roots:
			candidate_roots.extend((Path.cwd(), DEFAULT_DEVELOPMENT_ROOT))

		unique_roots: list[Path] = []
		seen_paths: set[str] = set()
		for candidate_root in candidate_roots:
			resolved_root = candidate_root.expanduser().resolve()
			path_key = str(resolved_root).casefold()
			if path_key not in seen_paths and resolved_root.exists():
				seen_paths.add(path_key)
				unique_roots.append(resolved_root)
		return unique_roots

	def _findClients(self, roots: list[Path], max_depth: int) -> list[Path]:
		matches: list[Path] = []
		seen_matches: set[str] = set()
		for root in roots:
			for directory_path, directory_names, _ in os.walk(root):
				current_path = Path(directory_path)
				depth = len(current_path.relative_to(root).parts)
				if depth >= max_depth:
					directory_names.clear()
				if self._isClientRoot(current_path):
					match_key = str(current_path).casefold()
					if match_key not in seen_matches:
						seen_matches.add(match_key)
						matches.append(current_path)
		return sorted(matches, key=lambda path: str(path).casefold())

	def _isClientRoot(self, candidate_path: Path) -> bool:
		return all((candidate_path / marker).is_file() for marker in PACKAGE_MARKERS)


def parseArguments() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description=(
			"Locate a generated Pulsonix Python client. The bundled library tools use "
			"the named pipe directly and do not require this package."
		)
	)
	parser.add_argument(
		"--root",
		action="append",
		default=[],
		help="Bounded search root; repeat to search more than one directory",
	)
	parser.add_argument(
		"--max-depth",
		type=int,
		default=6,
		help="Maximum directory depth below each root (default: 6)",
	)
	return parser.parse_args()


def main() -> int:
	return PulsonixClientFinder.getInstance().run(parseArguments())


if __name__ == "__main__":
	sys.exit(main())
