import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple


def run(cmd: List[str], cwd: Path | None = None, env: Dict[str, str] | None = None) -> str:
	"""Run a command and return stdout (raises on non-zero exit)."""
	res = subprocess.run(
		cmd,
		cwd=str(cwd) if cwd else None,
		env=env,
		check=True,
		capture_output=True,
		text=True,
	)
	return res.stdout.strip()


def git(cmd: List[str], repo_dir: Path) -> str:
	"""Convenience wrapper for git commands scoped to 'repo_dir'."""
	return run(["git", *cmd], cwd=repo_dir)


def setup_conflicted_repo(
	clone_url_with_token: str,
	out_dir: Path,
	base_ref: str,
	head_ref: str,
	base_sha_opt: str,
	head_sha_opt: str,
	head_clone_url_with_token: str | None,
) -> Tuple[str, str, str, bool]:
	"""Clone repo directly to out_dir and set up merge state using SHAs.

	Returns (base_sha, head_sha, merge_base, had_conflicts)
	"""
	# Ensure a clean workspace directory, then clone directly to /ws/out
	try:
		if out_dir.exists():
			shutil.rmtree(out_dir, ignore_errors=True)
		out_dir.parent.mkdir(parents=True, exist_ok=True)
	except Exception:
		pass
	# Clone the repo directly to /ws/out
	run(["git", "clone", clone_url_with_token, str(out_dir)])
	# Ensure commit identity is set for merge commits inside the repo
	git(["config", "user.name", "resbot"], out_dir)
	git(["config", "user.email", "resbot@noreply.local"], out_dir)

	# Require exact SHAs and ensure objects exist locally
	if not base_sha_opt or not head_sha_opt:
		raise RuntimeError("BASE_SHA and HEAD_SHA are required")
	# Fetch base SHA from origin (best-effort)
	try:
		git(["fetch", "origin", base_sha_opt], out_dir)
	except subprocess.CalledProcessError:
		pass
	base_sha = base_sha_opt
	# Fetch head SHA from origin or fork
	fetched = False
	try:
		git(["fetch", "origin", head_sha_opt], out_dir)
		fetched = True
	except subprocess.CalledProcessError:
		fetched = False
	if not fetched and head_clone_url_with_token:
		try:
			git(["remote", "add", "fork", head_clone_url_with_token], out_dir)
		except subprocess.CalledProcessError:
			pass
		git(["fetch", "fork", head_sha_opt], out_dir)
	head_sha = head_sha_opt

	# Compute merge-base using the available refs/objects (best-effort)
	try:
		merge_base = git(["merge-base", base_sha, head_sha], out_dir)
	except subprocess.CalledProcessError:
		merge_base = ""

	# Checkout base and attempt merge (leave index/worktree changed, no commit)
	# Using --no-commit ensures HEAD does not advance; Codex can then make edits
	# against a consistent tree even when the merge is clean.
	git(["checkout", "-B", "resbot/work", base_sha], out_dir)

	# Capture presence of objects and head before
	def obj_present(sha: str) -> bool:
		try:
			git(["cat-file", "-t", sha], out_dir)
			return True
		except subprocess.CalledProcessError:
			return False

	base_present = obj_present(base_sha)
	head_present = obj_present(head_sha)
	head_before = ""
	try:
		head_before = git(["rev-parse", "HEAD"], out_dir)
	except subprocess.CalledProcessError:
		head_before = ""

	# Run merge without raising to capture exact failure
	merge_res = subprocess.run(
		["git", "merge", "--no-ff", head_sha],
		cwd=str(out_dir),
		text=True,
		capture_output=True,
	)
	exit_code = merge_res.returncode
	head_after = ""
	try:
		head_after = git(["rev-parse", "HEAD"], out_dir)
	except subprocess.CalledProcessError:
		head_after = ""
	merge_head_exists = (out_dir / ".git" / "MERGE_HEAD").exists()
	try:
		unmerged = git(["ls-files", "-u"], out_dir)
	except subprocess.CalledProcessError:
		unmerged = ""
	try:
		conflicted_paths = git(["diff", "--name-only", "--diff-filter=U"], out_dir)
	except subprocess.CalledProcessError:
		conflicted_paths = ""

	unmerged_entries_count = len([l for l in unmerged.splitlines() if l.strip()])
	# True conflict only if merge left MERGE_HEAD or unmerged entries
	had_conflicts = merge_head_exists or (unmerged_entries_count > 0)

	# Telemetry: record exact merge attempt details
	try:
		# Persist merge telemetry outside the Git worktree so it never leaks into
		# user commits. The /ws volume is mounted for inspection after runs.
		merge_state_dir = Path("/ws/.resbot")
		merge_state_dir.mkdir(parents=True, exist_ok=True)
		telemetry = {
			"base_sha": base_sha,
			"head_sha": head_sha,
			"merge_base": merge_base,
			"exit_code": exit_code,
			"stdout_tail": (merge_res.stdout or "")[-2000:],
			"stderr_tail": (merge_res.stderr or "")[-2000:],
			"head_before": head_before,
			"head_after": head_after,
			"base_present": base_present,
			"head_present": head_present,
			"merge_head_exists": merge_head_exists,
			"unmerged_entries_count": unmerged_entries_count,
			"conflicted_paths": [p for p in conflicted_paths.splitlines() if p.strip()],
			"had_conflicts": had_conflicts,
		}
		(merge_state_dir / "merge_state.json").write_text(
			json.dumps(telemetry, indent=2), encoding="utf-8"
		)
		print(f"[resbot] merge telemetry: {telemetry}")
	except Exception:
		pass

	return base_sha, head_sha, merge_base, had_conflicts


def check_for_conflict_markers(out_dir: Path) -> bool:
	"""Check if any conflict markers remain in the repository."""
	try:
		# Use grep -q so we only care about the exit code, not the matched paths.
		run(
			["grep", "-r", "-q", "-E", "^<<<<<<<|^=======|^>>>>>>>"],
			cwd=out_dir,
		)
		# Exit code 0 means at least one match (conflict marker) was found.
		return True
	except subprocess.CalledProcessError:
		# grep returns non-zero when no matches found
		return False


