"""Dependency-free client for Pulsonix's local scripting named pipe."""

import ctypes
from ctypes import wintypes
import json
import time
from typing import Any


PIPE_PATH = r"\\.\pipe\PulsonixScripting"
PIPE_READMODE_MESSAGE = 0x00000002
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
MAX_RESPONSE_SIZE = 1024 * 1024


class PulsonixPipeError(RuntimeError):
	"""Raised when Pulsonix rejects a request or the named pipe is unavailable."""


class PulsonixPipeClient:
	"""Send standard scripting calls without requiring the generated client."""

	_instance: "PulsonixPipeClient | None" = None

	def __init__(self) -> None:
		self.handle: int | None = None
		self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
		self._configureWindowsApi()

	@classmethod
	def getInstance(cls) -> "PulsonixPipeClient":
		if cls._instance is None:
			cls._instance = cls()
		return cls._instance

	def _configureWindowsApi(self) -> None:
		self.kernel32.CreateFileW.argtypes = [
			wintypes.LPCWSTR,
			wintypes.DWORD,
			wintypes.DWORD,
			wintypes.LPVOID,
			wintypes.DWORD,
			wintypes.DWORD,
			wintypes.HANDLE,
		]
		self.kernel32.CreateFileW.restype = wintypes.HANDLE
		self.kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
		self.kernel32.WaitNamedPipeW.restype = wintypes.BOOL
		self.kernel32.SetNamedPipeHandleState.argtypes = [
			wintypes.HANDLE,
			ctypes.POINTER(wintypes.DWORD),
			wintypes.LPVOID,
			wintypes.LPVOID,
		]
		self.kernel32.SetNamedPipeHandleState.restype = wintypes.BOOL
		self.kernel32.WriteFile.argtypes = [
			wintypes.HANDLE,
			wintypes.LPCVOID,
			wintypes.DWORD,
			ctypes.POINTER(wintypes.DWORD),
			wintypes.LPVOID,
		]
		self.kernel32.WriteFile.restype = wintypes.BOOL
		self.kernel32.PeekNamedPipe.argtypes = [
			wintypes.HANDLE,
			wintypes.LPVOID,
			wintypes.DWORD,
			wintypes.LPVOID,
			ctypes.POINTER(wintypes.DWORD),
			wintypes.LPVOID,
		]
		self.kernel32.PeekNamedPipe.restype = wintypes.BOOL
		self.kernel32.ReadFile.argtypes = [
			wintypes.HANDLE,
			wintypes.LPVOID,
			wintypes.DWORD,
			ctypes.POINTER(wintypes.DWORD),
			wintypes.LPVOID,
		]
		self.kernel32.ReadFile.restype = wintypes.BOOL
		self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
		self.kernel32.CloseHandle.restype = wintypes.BOOL

	def connect(self, timeout_seconds: float = 5.0) -> None:
		if self.handle is not None:
			return
		timeout_milliseconds = max(1, int(timeout_seconds * 1000))
		if not self.kernel32.WaitNamedPipeW(PIPE_PATH, timeout_milliseconds):
			error_code = ctypes.get_last_error()
			raise PulsonixPipeError(
				"Pulsonix scripting pipe is unavailable "
				f"(Windows error {error_code}); enable Tools > Scripting Dashboard"
			)
		handle = self.kernel32.CreateFileW(
			PIPE_PATH,
			GENERIC_READ | GENERIC_WRITE,
			0,
			None,
			OPEN_EXISTING,
			0,
			None,
		)
		if handle == INVALID_HANDLE_VALUE:
			raise PulsonixPipeError(
				f"Pulsonix pipe connection failed with Windows error {ctypes.get_last_error()}"
			)
		read_mode = wintypes.DWORD(PIPE_READMODE_MESSAGE)
		if not self.kernel32.SetNamedPipeHandleState(
			handle,
			ctypes.byref(read_mode),
			None,
			None,
		):
			self.kernel32.CloseHandle(handle)
			raise PulsonixPipeError(
				f"Pulsonix pipe configuration failed with Windows error {ctypes.get_last_error()}"
			)
		self.handle = handle

	def close(self) -> None:
		if self.handle is not None:
			self.kernel32.CloseHandle(self.handle)
			self.handle = None

	def call(
		self,
		function_name: str,
		*arguments: Any,
		object_id: int = 0,
		timeout_seconds: float = 120.0,
	) -> Any:
		return self._request(
			{
				"func": function_name,
				"id": object_id,
				"args": list(arguments),
			},
			timeout_seconds,
		)

	def get(
		self,
		object_id: int,
		property_name: str,
		timeout_seconds: float = 30.0,
	) -> Any:
		return self._request(
			{"get": property_name, "id": object_id},
			timeout_seconds,
		)

	def _request(self, request_data: dict[str, Any], timeout_seconds: float) -> Any:
		self.connect()
		if self.handle is None:
			raise PulsonixPipeError("Pulsonix pipe request failed because no handle exists")
		message = json.dumps(request_data, separators=(",", ":")).encode("utf-8")
		message_buffer = ctypes.create_string_buffer(message)
		bytes_written = wintypes.DWORD()
		if not self.kernel32.WriteFile(
			self.handle,
			message_buffer,
			len(message),
			ctypes.byref(bytes_written),
			None,
		):
			error_code = ctypes.get_last_error()
			self.close()
			raise PulsonixPipeError(
				f"Pulsonix pipe write failed with Windows error {error_code}"
			)
		if bytes_written.value != len(message):
			self.close()
			raise PulsonixPipeError("Pulsonix received an incomplete request")

		response_data = self._readResponse(timeout_seconds)
		if "err" in response_data:
			error_code = response_data.get("code", "unknown")
			error_type = response_data.get("type", "non-fatal")
			raise PulsonixPipeError(
				f"Pulsonix rejected the request: {response_data['err']} "
				f"(code {error_code}, {error_type})"
			)
		return response_data.get("val")

	def _readResponse(self, timeout_seconds: float) -> dict[str, Any]:
		if self.handle is None:
			raise PulsonixPipeError("Pulsonix response read failed because no handle exists")
		deadline = time.monotonic() + timeout_seconds
		available_bytes = wintypes.DWORD()
		while time.monotonic() < deadline:
			if not self.kernel32.PeekNamedPipe(
				self.handle,
				None,
				0,
				None,
				ctypes.byref(available_bytes),
				None,
			):
				error_code = ctypes.get_last_error()
				self.close()
				raise PulsonixPipeError(
					f"Pulsonix pipe read failed with Windows error {error_code}"
				)
			if available_bytes.value:
				if available_bytes.value > MAX_RESPONSE_SIZE:
					self.close()
					raise PulsonixPipeError("Pulsonix returned an oversized response")
				response_buffer = ctypes.create_string_buffer(available_bytes.value)
				bytes_read = wintypes.DWORD()
				if not self.kernel32.ReadFile(
					self.handle,
					response_buffer,
					available_bytes.value,
					ctypes.byref(bytes_read),
					None,
				):
					error_code = ctypes.get_last_error()
					self.close()
					raise PulsonixPipeError(
						f"Pulsonix pipe response failed with Windows error {error_code}"
					)
				try:
					response = json.loads(
						response_buffer.raw[: bytes_read.value].decode("utf-8")
					)
				except Exception as error:
					self.close()
					raise PulsonixPipeError(
						f"Pulsonix returned invalid JSON because {error}"
					) from error
				if not isinstance(response, dict):
					self.close()
					raise PulsonixPipeError("Pulsonix returned a non-object response")
				return response
			time.sleep(0.02)
		self.close()
		raise TimeoutError(
			f"Pulsonix did not respond within {timeout_seconds:.1f} seconds"
		)
