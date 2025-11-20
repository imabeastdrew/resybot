import os
import subprocess
from pathlib import Path
from typing import List, Tuple

from .git import run as run_cmd


def ensure_codex_login(
	codex_bin: str,
	codex_home: str,
	xdg_state_home: str,
	openai_api_key: str | None,
) -> Tuple[bool, str, int]:
	"""Ensure Codex is authenticated using the provided API key.

	Returns (ok, error_message, exit_code).
	- ok=True when authentication is already configured or succeeds.
	- If OPENAI_API_KEY is missing, returns (False, "missing_api_key", 0).
	- If login fails, returns (False, stderr_tail, exit_code).
	"""
	auth_json_path = Path(codex_home) / "auth.json"
	if auth_json_path.exists():
		return True, "", 0

	if not openai_api_key:
		return False, "missing_api_key", 0

	# Ensure CODEX_HOME and XDG_STATE_HOME directories exist
	Path(codex_home).mkdir(parents=True, exist_ok=True)
	Path(xdg_state_home).mkdir(parents=True, exist_ok=True)
	# Codex writes history under ${XDG_STATE_HOME}/codex/history.jsonl
	Path(xdg_state_home, "codex").mkdir(parents=True, exist_ok=True)

	# Run codex login --with-api-key by piping the API key to stdin
	login_process = subprocess.Popen(
		[codex_bin, "login", "--with-api-key"],
		stdin=subprocess.PIPE,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		env={
			**os.environ,
			"CODEX_HOME": codex_home,
			"XDG_STATE_HOME": xdg_state_home,
		},
		text=True,
	)
	_stdout, stderr = login_process.communicate(input=openai_api_key)
	if login_process.returncode != 0:
		stderr_tail = (stderr or "")[-2000:]
		return False, stderr_tail, login_process.returncode

	return True, "", 0


def build_merge_prompt(
	num_conflicts: int,
	conflicted_paths_list: List[str],
	extra_instructions: str,
) -> str:
	"""Build the LLM prompt describing conflicts and any user instructions."""
	num_conflict_files = len(conflicted_paths_list)
	conflicted_listing = "\n".join(f"- {p}" for p in conflicted_paths_list)
	merge_prompt = (
		f"Resolve {num_conflicts} conflicts across {num_conflict_files} files by editing them in place.\n"
		f"Only edit these files:\n{conflicted_listing}\n"
	)
	extra_instructions = (extra_instructions or "").strip()
	if extra_instructions:
		merge_prompt = (
			f"{merge_prompt}\n"
			f"Additional user instructions from the PR comment:\n"
			f"{extra_instructions}\n"
		)
	return merge_prompt


def run_codex_exec(
	codex_bin: str,
	prompt: str,
	out_dir: Path,
	codex_home: str,
	xdg_state_home: str,
) -> str:
	"""Invoke Codex in the conflicted repo and persist stdout for debugging."""
	codex_stdout = run_cmd(
		[codex_bin, "exec", prompt],
		cwd=out_dir,
		env={
			**os.environ,
			"CODEX_HOME": codex_home,
			"XDG_STATE_HOME": xdg_state_home,
			"SHELL": "/bin/bash",
		},
	)

	# Persist exec stdout for debugging
	try:
		Path(xdg_state_home).mkdir(parents=True, exist_ok=True)
		(Path(xdg_state_home) / "codex").mkdir(parents=True, exist_ok=True)
		(Path(xdg_state_home) / "codex" / "exec.log").write_text(
			codex_stdout, encoding="utf-8"
		)
	except Exception:
		pass

	return codex_stdout


