"""Runtime helpers shared by Pulsonix skill scripts."""

import importlib
import logging
from pathlib import Path
import sys
from types import ModuleType


class BelowErrorFilter(logging.Filter):
	"""Keep error records out of the standard-output logging handler."""

	def filter(self, record: logging.LogRecord) -> bool:
		return record.levelno < logging.ERROR


class RuntimeSupport:
	"""Configure logging and load the generated Pulsonix Python client."""

	_instance: "RuntimeSupport | None" = None

	@classmethod
	def getInstance(cls) -> "RuntimeSupport":
		if cls._instance is None:
			cls._instance = cls()
		return cls._instance

	def configureLogging(self, logger_name: str) -> logging.Logger:
		logger = logging.getLogger(logger_name)
		if logger.handlers:
			return logger

		logger.setLevel(logging.INFO)
		logger.propagate = False
		formatter = logging.Formatter("%(levelname)s %(message)s")

		stdout_handler = logging.StreamHandler(sys.stdout)
		stdout_handler.setLevel(logging.INFO)
		stdout_handler.addFilter(BelowErrorFilter())
		stdout_handler.setFormatter(formatter)
		logger.addHandler(stdout_handler)

		stderr_handler = logging.StreamHandler(sys.stderr)
		stderr_handler.setLevel(logging.ERROR)
		stderr_handler.setFormatter(formatter)
		logger.addHandler(stderr_handler)
		return logger

	def loadPulsonix(self, client_path: Path) -> ModuleType:
		resolved_client_path = client_path.resolve()
		package_file = resolved_client_path / "pulsonix" / "__init__.py"
		if not package_file.is_file():
			raise FileNotFoundError(
				f"Pulsonix client load failed because {package_file} does not exist"
			)
		client_path_text = str(resolved_client_path)
		if client_path_text not in sys.path:
			sys.path.insert(0, client_path_text)
		return importlib.import_module("pulsonix")
