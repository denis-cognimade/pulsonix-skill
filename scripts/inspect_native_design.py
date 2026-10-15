"""Snapshot any CFB design/library and inventory logical streams offline."""

import argparse
from pathlib import Path
import sys

from modules.native_archive import NativeArchive
from modules.native_editor import NativeEditor
from modules.native_storage import NativeStorage
from modules.runtime import RuntimeSupport


def main() -> int:
	logger = RuntimeSupport.getInstance().configureLogging("pulsonix.native_inspector")
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--source", type=Path, required=True)
	parser.add_argument("--output", type=Path, required=True, help="New investigation directory")
	arguments = parser.parse_args()
	try:
		data = arguments.source.read_bytes()
		streams = NativeStorage.readBytes(data)
		arguments.output.mkdir(parents=True, exist_ok=False)
		(arguments.output / f"source{arguments.source.suffix}").write_bytes(data)
		manifest = {"source": str(arguments.source.resolve()), "source_sha256": NativeStorage.hashBytes(data),
			"source_bytes": len(data), "streams": NativeStorage.manifest(streams), "application_calls": False}
		for index, item in enumerate(manifest["streams"]):
			stream_data = streams[tuple(item["path"])]
			filename = f"stream_{index:03d}.bin"
			(arguments.output / filename).write_bytes(stream_data)
			inventory = NativeArchive.inventory(stream_data)
			NativeEditor.writeJson(arguments.output / f"stream_{index:03d}_inventory.json", inventory)
			item["file"] = filename
			item["string_candidates"] = len(inventory["strings"])
			item["class_declarations"] = inventory["class_declarations"]
		NativeEditor.writeJson(arguments.output / "manifest.json", manifest)
		if arguments.source.read_bytes() != data:
			raise ValueError("Source changed during inspection; snapshot is retained but offsets are stale")
		logger.info("Inventoried %s streams in %s", len(streams), arguments.output)
		return 0
	except Exception as error:
		logger.error("Native inspection stopped because %s", error)
		return 1


if __name__ == "__main__":
	sys.exit(main())
