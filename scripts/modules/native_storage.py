"""Offline Windows compound-storage IO; never connects to Pulsonix."""

import hashlib
from pathlib import Path
import tempfile
from typing import Any

CFB_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")


class NativeStorage:
	@staticmethod
	def hashBytes(data: bytes) -> str:
		return hashlib.sha256(data).hexdigest()

	@staticmethod
	def readStorage(storage: Any, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], bytes]:
		streams = {}
		for item in storage.EnumElements():
			name, element_type, size = item[:3]
			path = (*prefix, name)
			if element_type == 1:
				child = storage.OpenStorage(name, None, 16, None, 0)
				try:
					streams.update(NativeStorage.readStorage(child, path))
				finally:
					child = None
			elif element_type == 2:
				stream = storage.OpenStream(name, None, 16, 0)
				try:
					streams[path] = stream.Read(size)
					if len(streams[path]) != size:
						raise IOError(f"Short read of compound stream {path}")
				finally:
					stream = None
		return streams

	@staticmethod
	def readBytes(data: bytes) -> dict[tuple[str, ...], bytes]:
		if not data.startswith(CFB_SIGNATURE):
			raise ValueError("Unsupported file: expected an OLE Compound File")
		import pythoncom
		# A byte-identical snapshot avoids the application's structured-storage locks.
		with tempfile.TemporaryDirectory(prefix="pulsonix_native_read_") as directory:
			snapshot = Path(directory) / "snapshot.bin"
			snapshot.write_bytes(data)
			storage = pythoncom.StgOpenStorage(str(snapshot), None, 32, None, 0)
			try:
				return NativeStorage.readStorage(storage)
			finally:
				storage = None

	@staticmethod
	def readFile(path: Path) -> dict[tuple[str, ...], bytes]:
		return NativeStorage.readBytes(path.read_bytes())

	@staticmethod
	def writeContents(path: Path, data: bytes) -> None:
		if path.suffix.lower() != ".sch":
			raise ValueError("Native writer supports schematic copies (.sch) only")
		import pythoncom
		storage = pythoncom.StgOpenStorage(str(path.resolve()), None, 18, None, 0)
		try:
			stream = storage.OpenStream("Contents", None, 18, 0)
			try:
				stream.Seek(0, 0)
				if stream.Write(data) != len(data):
					raise IOError("Incomplete Contents write")
				stream.SetSize(len(data))
				stream.Commit(0)
			finally:
				stream = None
			storage.Commit(0)
		finally:
			storage = None

	@staticmethod
	def manifest(streams: dict[tuple[str, ...], bytes]) -> list[dict[str, Any]]:
		return [{"path": list(path), "size": len(data), "sha256": NativeStorage.hashBytes(data)}
			for path, data in sorted(streams.items())]
