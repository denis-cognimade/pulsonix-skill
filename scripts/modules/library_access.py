"""Check native-library write access without changing files or contacting Pulsonix."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path


class NativeLibraryAccess:
	"""Reject locked and read-only native files before starting API automation."""

	_instance: "NativeLibraryAccess | None" = None

	@classmethod
	def getInstance(cls) -> "NativeLibraryAccess":
		if cls._instance is None:
			cls._instance = cls()
		return cls._instance

	def requireWritableLibrary(self, library_path: Path) -> None:
		self._requireWritableFile(library_path)
		index_path = library_path.with_suffix(".palx")
		if index_path.exists():
			self._requireWritableFile(index_path)

	def _requireWritableFile(self, path: Path) -> None:
		if not path.is_file():
			raise FileNotFoundError(f"Library access check failed because {path} does not exist")
		if os.name != "nt":
			with path.open("r+b"):
				pass
			return

		kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
		kernel32.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
		kernel32.GetFileAttributesW.restype = wintypes.DWORD
		kernel32.CreateFileW.argtypes = [
			wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
			wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
		]
		kernel32.CreateFileW.restype = wintypes.HANDLE
		kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
		kernel32.CloseHandle.restype = wintypes.BOOL

		attributes = kernel32.GetFileAttributesW(str(path))
		if attributes == 0xFFFFFFFF:
			error_code = ctypes.get_last_error()
			raise OSError(error_code, f"Library access check failed for {path}: {ctypes.FormatError(error_code).strip()}")
		if attributes & 0x00000001:
			raise PermissionError(f"Library is unwritable because the file is read-only: {path}. Pulsonix API was not contacted.")

		handle = kernel32.CreateFileW(
			str(path),
			0x40000000,  # GENERIC_WRITE; no writes are performed.
			0x00000007,  # Share read, write, and delete access.
			None,
			3,           # OPEN_EXISTING; never create or truncate.
			0,
			None,
		)
		if handle == wintypes.HANDLE(-1).value:
			error_code = ctypes.get_last_error()
			if error_code in (32, 33):
				raise PermissionError(f"Library is locked and cannot be written right now: {path} (Windows error {error_code}). Pulsonix API was not contacted; release the file lock before retrying.")
			if error_code == 5:
				raise PermissionError(f"Library is unwritable because write access is denied: {path} (Windows error 5). Pulsonix API was not contacted.")
			raise OSError(error_code, f"Library access check failed for {path}: {ctypes.FormatError(error_code).strip()}")
		if not kernel32.CloseHandle(handle):
			error_code = ctypes.get_last_error()
			raise OSError(error_code, f"Library access probe could not release its file handle for {path}")
