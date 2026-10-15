"""Exercise write-access guards using temporary files, never a live Pulsonix API."""

import argparse
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_component_plx import ComponentPlxImporter
from modules.library_access import NativeLibraryAccess


class LibraryAccessTests(unittest.TestCase):
	"""Check that filesystem failures stop imports before any API acquisition."""

	def createFixture(self, directory: Path) -> argparse.Namespace:
		library = directory / "parts.pal"
		library.write_bytes(b"unchanged native library fixture")
		library.with_suffix(".palx").write_bytes(b"unchanged index fixture")
		plx_directory = directory / "plx"
		plx_directory.mkdir()
		(plx_directory / "example.plx").write_text(
			'(compDef "Example" (compHeader (numPins 2))\n'
			'(attachedSymbol (partNum 1) (symbolName "Resistor"))\n'
			'(attachedPattern (patternNum 1) (patternName "R0402")))\n',
			encoding="utf-8",
		)
		return argparse.Namespace(library=str(library), plx_directory=str(plx_directory), backup_directory=None)

	def getWindowsApi(self) -> ctypes.CDLL:
		kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
		kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
		kernel32.CreateFileW.restype = wintypes.HANDLE
		kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
		kernel32.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
		kernel32.GetFileAttributesW.restype = wintypes.DWORD
		kernel32.SetFileAttributesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
		return kernel32

	def assertBlockedBeforeApi(self, arguments: argparse.Namespace, reason: str) -> None:
		importer = ComponentPlxImporter()
		with patch("import_component_plx.PulsonixPipeClient.getInstance") as api_acquisition:
			with self.assertLogs(importer.logger, level="ERROR") as captured:
				result = importer.run(arguments)
			self.assertEqual(result, 1)
			api_acquisition.assert_not_called()
			self.assertIn(reason, "\n".join(captured.output))
			self.assertIn("Pulsonix API was not contacted", "\n".join(captured.output))

	def checkLockedFile(self, suffix: str) -> None:
		if os.name != "nt":
			self.skipTest("Windows file sharing test")
		with tempfile.TemporaryDirectory() as directory:
			arguments = self.createFixture(Path(directory))
			locked_file = Path(arguments.library).with_suffix(suffix)
			contents = locked_file.read_bytes()
			kernel32 = self.getWindowsApi()
			handle = kernel32.CreateFileW(str(locked_file), 0x80000000, 0, None, 3, 0, None)
			self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
			try:
				self.assertBlockedBeforeApi(arguments, "locked and cannot be written")
			finally:
				kernel32.CloseHandle(handle)
			self.assertEqual(locked_file.read_bytes(), contents)

	def testLockedNativeLibraryStopsBeforeApi(self) -> None:
		self.checkLockedFile(".pal")

	def testLockedIndexStopsBeforeApi(self) -> None:
		self.checkLockedFile(".palx")

	def testReadOnlyLibraryStopsBeforeApi(self) -> None:
		if os.name != "nt":
			self.skipTest("Windows read-only attribute test")
		with tempfile.TemporaryDirectory() as directory:
			arguments = self.createFixture(Path(directory))
			library = Path(arguments.library)
			contents = library.read_bytes()
			kernel32 = self.getWindowsApi()
			attributes = kernel32.GetFileAttributesW(str(library))
			self.assertTrue(kernel32.SetFileAttributesW(str(library), attributes | 1))
			try:
				self.assertBlockedBeforeApi(arguments, "file is read-only")
			finally:
				kernel32.SetFileAttributesW(str(library), attributes)
			self.assertEqual(library.read_bytes(), contents)

	def testWritableProbePreservesFiles(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			arguments = self.createFixture(Path(directory))
			library = Path(arguments.library)
			paths = [library, library.with_suffix(".palx")]
			before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
			NativeLibraryAccess.getInstance().requireWritableLibrary(library)
			after = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
			self.assertEqual(before, after)


if __name__ == "__main__":
	unittest.main()
