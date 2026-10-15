"""Extract PLX files from ZIP archives under the current directory."""

import logging
import sys
import zipfile
from pathlib import Path, PurePosixPath


class PlxArchiveExtractor:
	"""Find ZIP archives recursively and extract their PLX files to the root."""

	_instance: "PlxArchiveExtractor | None" = None

	@classmethod
	def getInstance(cls) -> "PlxArchiveExtractor":
		if cls._instance is None:
			cls._instance = cls()
		return cls._instance

	def __init__(self) -> None:
		self.root_directory = Path.cwd()
		self.logger = logging.getLogger("plx_archive_extractor")

	def findZipFiles(self) -> list[Path]:
		try:
			return sorted(
				(
					path
					for path in self.root_directory.rglob("*")
					if path.is_file() and path.suffix.casefold() == ".zip"
				),
				key=lambda path: str(path).casefold(),
			)
		except Exception:
			self.logger.exception("Could not search for ZIP files under %s", self.root_directory)
			return []

	def extractArchive(self, archive_path: Path, reserved_names: set[str]) -> int:
		extracted_count = 0
		try:
			with zipfile.ZipFile(archive_path) as archive:
				for member in archive.infolist():
					if member.is_dir():
						continue

					member_name = member.filename.replace("\\", "/")
					file_name = PurePosixPath(member_name).name
					if not file_name or file_name in {".", ".."}:
						continue
					if PurePosixPath(file_name).suffix.casefold() != ".plx":
						continue

					name_key = file_name.casefold()
					if name_key in reserved_names:
						self.logger.warning(
							"Skipping %s in %s because %s already exists",
							member.filename,
							archive_path,
							file_name,
						)
						continue

					output_path = self.root_directory / file_name
					try:
						contents = archive.read(member)
						with output_path.open("xb") as output_file:
							output_file.write(contents)
					except FileExistsError:
						reserved_names.add(name_key)
						self.logger.warning("Skipping %s because %s already exists", member.filename, output_path)
						continue
					except Exception:
						self.logger.exception("Could not extract %s from %s", member.filename, archive_path)
						continue

					reserved_names.add(name_key)
					extracted_count += 1
					self.logger.info("Extracted %s", output_path)
		except Exception:
			self.logger.exception("Could not read ZIP archive %s", archive_path)

		return extracted_count

	def run(self) -> int:
		zip_files = self.findZipFiles()
		if not zip_files:
			self.logger.info("No ZIP files found under %s", self.root_directory)
			return 0

		try:
			reserved_names = {
				path.name.casefold()
				for path in self.root_directory.iterdir()
				if path.is_file()
			}
		except Exception:
			self.logger.exception("Could not inspect output directory %s", self.root_directory)
			return 1

		extracted_count = 0
		for archive_path in zip_files:
			extracted_count += self.extractArchive(archive_path, reserved_names)

		self.logger.info(
			"Finished: extracted %s PLX file(s) from %s ZIP file(s)",
			extracted_count,
			len(zip_files),
		)
		return 0


def main() -> int:
	logging.basicConfig(
		level=logging.INFO,
		format="%(levelname)s: %(message)s",
		stream=sys.stdout,
	)
	return PlxArchiveExtractor.getInstance().run()


if __name__ == "__main__":
	raise SystemExit(main())

