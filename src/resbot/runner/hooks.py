import os
import shlex
from pathlib import Path

from .git import run


def run_optional_hooks(out_dir: Path) -> None:
	"""Run optional post-resolution hooks if enabled."""
	# Install dependencies
	install_cmd = os.environ.get("INSTALL_CMD")
	if os.environ.get("ENABLE_DEPS_INSTALL", "").lower() == "true" and install_cmd:
		print(f"Running install command: {install_cmd}")
		run(shlex.split(install_cmd), cwd=out_dir)

	# Format code
	format_cmd = os.environ.get("FORMAT_CMD")
	if os.environ.get("ENABLE_FORMAT", "").lower() == "true" and format_cmd:
		print(f"Running format command: {format_cmd}")
		run(shlex.split(format_cmd), cwd=out_dir)

	# Run tests
	test_cmd = os.environ.get("TEST_CMD")
	if os.environ.get("ENABLE_TESTS", "").lower() == "true" and test_cmd:
		print(f"Running test command: {test_cmd}")
		run(shlex.split(test_cmd), cwd=out_dir)


