import os
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import jwt
import requests


@dataclass
class RunnerConfig:
	"""Runtime configuration passed in via environment variables.

	All fields map 1:1 to env vars set by the server when spawning the runner.
	"""
	repo_full: str
	clone_url: str
	pr_number: int
	base_ref: str
	head_ref: str
	# Optional exact SHAs and head repo URL for fork PRs
	base_sha_opt: str
	head_sha_opt: str
	head_clone_url_opt: str
	installation_id: int
	github_app_id: str
	github_private_key: str
	max_repo_mb: int
	max_exec_seconds: int
	max_file_mb: int
	# Optional free-form instructions provided via /resybot issue comments
	user_prompt: str = ""


def read_env_config() -> RunnerConfig:
	"""Load and validate required environment variables for this run."""
	def req(name: str) -> str:
		val = os.environ.get(name)
		if not val:
			raise RuntimeError(f"Missing env: {name}")
		return val

	return RunnerConfig(
		repo_full=req("REPO_FULL"),
		clone_url=req("CLONE_URL"),
		pr_number=int(req("PR_NUMBER")),
		base_ref=req("BASE_REF"),
		head_ref=req("HEAD_REF"),
		base_sha_opt=os.environ.get("BASE_SHA", ""),
		head_sha_opt=os.environ.get("HEAD_SHA", ""),
		head_clone_url_opt=os.environ.get("HEAD_CLONE_URL", ""),
		installation_id=int(req("INSTALLATION_ID")),
		github_app_id=req("GITHUB_APP_ID"),
		github_private_key=req("GITHUB_PRIVATE_KEY"),
		max_repo_mb=int(os.environ.get("RESBOT_MAX_REPO_MB", "2000")),
		max_exec_seconds=int(os.environ.get("RESBOT_MAX_EXEC_SECONDS", "600")),
		max_file_mb=int(os.environ.get("RESBOT_MAX_FILE_MB", "10")),
		user_prompt=os.environ.get("USER_PROMPT", "") or "",
	)


def create_app_jwt(app_id: str, private_key: str) -> str:
	"""Create a short‑lived JWT used to request an installation token."""
	from time import time
	claims = {"iat": int(time()) - 60, "exp": int(time()) + 540, "iss": app_id}
	if "BEGIN" in private_key and "\\n" not in private_key and "\n" not in private_key:
		private_key = private_key.replace("\\n", "\n")
	return jwt.encode(claims, private_key, algorithm="RS256")


def get_installation_token(app_id: str, private_key: str, installation_id: int) -> str:
	"""Exchange the app JWT for an installation token (GitHub App auth)."""
	app_jwt = create_app_jwt(app_id, private_key)
	url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
	resp = requests.post(
		url,
		headers={
			"Authorization": f"Bearer {app_jwt}",
			"Accept": "application/vnd.github+json",
			"User-Agent": "resbot-runner",
		},
	)
	resp.raise_for_status()
	return resp.json()["token"]


def run(cmd: List[str], cwd: Path | None = None, env: Dict[str, str] | None = None) -> str:
	"""Run a command and return stdout (raises on non‑zero exit).

	The optional 'env' is required for tools like Codex that read config from
	environment variables (e.g., CODEX_HOME).
	"""
	res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True, capture_output=True, text=True)
	return res.stdout.strip()


def git(cmd: List[str], repo_dir: Path) -> str:
	"""Convenience wrapper for git commands scoped to 'repo_dir'."""
	return run(["git", *cmd], cwd=repo_dir)


def compute_shas(repo_dir: Path, base_ref: str, head_ref: str) -> Tuple[str, str, str]:
	"""Resolve base/head SHAs and their merge base, deepening history if needed."""
	base_sha = git(["rev-parse", f"origin/{base_ref}"], repo_dir)
	head_sha = git(["rev-parse", f"origin/{head_ref}"], repo_dir)
	try:
		merge_base = git(["merge-base", f"origin/{base_ref}", f"origin/{head_ref}"], repo_dir)
	except subprocess.CalledProcessError:
		# Shallow history may not include a common ancestor; deepen and retry
		try:
			git(["fetch", "origin", "--deepen", "1000000"], repo_dir)
		except subprocess.CalledProcessError:
			# Fallback to full unshallow if supported
			try:
				git(["fetch", "--unshallow"], repo_dir)
			except subprocess.CalledProcessError:
				pass
		merge_base = git(["merge-base", f"origin/{base_ref}", f"origin/{head_ref}"], repo_dir)
	return base_sha, head_sha, merge_base


 


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
		cwd=str(out_dir), text=True, capture_output=True
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
		result = run(["grep", "-r", "-l", "-E", "^<<<<<<<|^=======|^>>>>>>>" ] ,
					cwd=out_dir)
		return len(result.strip()) > 0
	except subprocess.CalledProcessError:
		# grep returns non-zero when no matches found
		return False


def run_optional_hooks(out_dir: Path) -> None:
	"""Run optional post-resolution hooks if enabled."""
	# Install dependencies
	install_cmd = os.environ.get("INSTALL_CMD")
	if os.environ.get("ENABLE_DEPS_INSTALL", "").lower() == "true" and install_cmd:
		print(f"Running install command: {install_cmd}")
		try:
			run(install_cmd.split(), cwd=out_dir)
		except subprocess.CalledProcessError as e:
			print(f"Install command failed: {e}")
			raise

	# Format code
	format_cmd = os.environ.get("FORMAT_CMD")
	if os.environ.get("ENABLE_FORMAT", "").lower() == "true" and format_cmd:
		print(f"Running format command: {format_cmd}")
		try:
			run(format_cmd.split(), cwd=out_dir)
		except subprocess.CalledProcessError as e:
			print(f"Format command failed: {e}")
			raise

	# Run tests
	test_cmd = os.environ.get("TEST_CMD")
	if os.environ.get("ENABLE_TESTS", "").lower() == "true" and test_cmd:
		print(f"Running test command: {test_cmd}")
		try:
			run(test_cmd.split(), cwd=out_dir)
		except subprocess.CalledProcessError as e:
			print(f"Test command failed: {e}")
			raise


def post_pr_comment(token: str, repo_full: str, pr_number: int, body: str) -> None:
	"""Comment on the source PR to report progress/failures back to users."""
	owner, repo = repo_full.split("/", 1)
	url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
	resp = requests.post(
		url,
		json={"body": body},
		headers={
			"Authorization": f"token {token}",
			"Accept": "application/vnd.github+json",
			"User-Agent": "resbot-runner",
		},
	)
	resp.raise_for_status()


def create_pull_request(
	token: str,
	repo_full: str,
	title: str,
	head: str,
	base: str,
	body: str,
) -> dict:
	"""Open a PR from our resolution branch into the base branch."""
	owner, repo = repo_full.split("/", 1)
	url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
	resp = requests.post(
		url,
		json={"title": title, "head": head, "base": base, "body": body},
		headers={
			"Authorization": f"token {token}",
			"Accept": "application/vnd.github+json",
			"User-Agent": "resbot-runner",
		},
	)
	resp.raise_for_status()
	return resp.json()


def main() -> None:
	"""End‑to‑end flow: reproduce merge, run Codex, validate, publish PR."""
	cfg = read_env_config()
	token = get_installation_token(cfg.github_app_id, cfg.github_private_key, cfg.installation_id)

	owner, repo = cfg.repo_full.split("/", 1)
	clone_url_with_token = cfg.clone_url.replace("https://", f"https://x-access-token:{token}@")

	out_dir = Path("/ws/out")

	try:
		# Clone repo directly to /ws/out and set up merge state using exact SHAs when provided
		head_clone_url_with_token = (
			cfg.clone_url.replace("https://", f"https://x-access-token:{token}@")
			if not cfg.head_clone_url_opt
			else cfg.head_clone_url_opt.replace("https://", f"https://x-access-token:{token}@")
		)
		base_sha, head_sha, merge_base, had_conflicts = setup_conflicted_repo(
			clone_url_with_token,
			out_dir,
			cfg.base_ref,
			cfg.head_ref,
			cfg.base_sha_opt,
			cfg.head_sha_opt,
			head_clone_url_with_token,
		)

		# Only act when there are conflicts; otherwise exit immediately
		if not had_conflicts:
			return

		# Codex integration - run in the conflicted repo (only when conflicts existed)
		codex_bin = os.environ.get("CODEX_BIN", "codex")
		codex_home = os.environ.get("CODEX_HOME", "/app/codex/config")
		xdg_state_home = os.environ.get("XDG_STATE_HOME", "/app/codex/state")
		# Ensure the runner process exports XDG_STATE_HOME so telemetry reader sees it
		os.environ["XDG_STATE_HOME"] = xdg_state_home
		openai_api_key = os.environ.get("OPENAI_API_KEY")
		
		# Ensure Codex is authenticated before running exec
		# We prefer API key auth; 'forced_login_method = "api"' in config enforces
		# non‑interactive login for CI.
		# Check if auth.json exists, if not, authenticate with API key
		auth_json_path = Path(codex_home) / "auth.json"
		if not auth_json_path.exists():
			if not openai_api_key:
				post_pr_comment(
					token,
					cfg.repo_full,
					cfg.pr_number,
					f"Missing OPENAI_API_KEY. Cannot authenticate Codex. Aborting. base={base_sha} head={head_sha} merge-base={merge_base}",
				)
				return
			
			# Authenticate Codex non-interactively using API key
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
			stdout, stderr = login_process.communicate(input=openai_api_key)
			if login_process.returncode != 0:
				post_pr_comment(
					token,
					cfg.repo_full,
					cfg.pr_number,
					f"Codex login failed (exit={login_process.returncode}). Aborting. base={base_sha} head={head_sha} merge-base={merge_base}\n\nError: {stderr[:500]}",
				)
				return
		
		# Build a constrained prompt: edit conflicted files in place only; no git ops
		num_conflict_files = 0
		conflicted_paths_list: List[str] = []
		if had_conflicts:
			try:
				_conf_out = git(["diff", "--name-only", "--diff-filter=U"], out_dir)
				conflicted_paths_list = [p for p in _conf_out.splitlines() if p.strip()]
				num_conflict_files = len(conflicted_paths_list)
			except subprocess.CalledProcessError:
				num_conflict_files = 0
		num_conflicts = 0
		try:
			_marker_out = run(["grep", "-R", "-n", "-E", "^<<<<<<<"], cwd=out_dir)
			num_conflicts = len([l for l in _marker_out.splitlines() if l.strip()])
		except subprocess.CalledProcessError:
			num_conflicts = 0
		conflicted_listing = "\n".join(f"- {p}" for p in conflicted_paths_list)
		merge_prompt = (
			f"Resolve {num_conflicts} conflicts across {num_conflict_files} files by editing them in place.\n"
			f"Only edit these files:\n{conflicted_listing}\n"
		)
		# If the run was triggered by a /resybot comment with extra instructions,
		# append that context to the merge prompt to guide the resolution.
		extra_instructions = (cfg.user_prompt or "").strip()
		if extra_instructions:
			merge_prompt = (
				f"{merge_prompt}\n"
				f"Additional user instructions from the PR comment:\n"
				f"{extra_instructions}\n"
			)

		# Codex integration - run in the conflicted repo (only when conflicts existed)
		# Before invoking Codex, record the initially conflicted paths so we can
		# verify that its resolution actually touches those files later.
		conflicted_paths: set[str] = set()
		if had_conflicts:
			# List paths with unresolved conflicts (U) before Codex runs
			_conf_out = git(["diff", "--name-only", "--diff-filter=U"], out_dir)
			conflicted_paths = set(p for p in _conf_out.splitlines() if p)

		codex_stdout: str = ""
		if had_conflicts:
			try:
				codex_stdout = run([codex_bin, "exec", merge_prompt], cwd=out_dir, env={
					**os.environ,
					"CODEX_HOME": codex_home,
					"XDG_STATE_HOME": xdg_state_home,
					"SHELL": "/bin/bash",
				})
				# Persist exec stdout for debugging
				try:
					(Path(xdg_state_home) / "codex").mkdir(parents=True, exist_ok=True)
					(Path(xdg_state_home) / "codex" / "exec.log").write_text(codex_stdout, encoding="utf-8")
				except Exception:
					pass
			except subprocess.CalledProcessError as e:
				# Attach stderr tail for debugging
				stderr_tail = (e.stderr or "")[-2000:] if hasattr(e, "stderr") else ""
				post_pr_comment(
					token,
					cfg.repo_full,
					cfg.pr_number,
					f"Codex failed (exit={e.returncode}). Aborting. base={base_sha} head={head_sha} merge-base={merge_base}\n\nCodex stderr tail:\n{stderr_tail}",
				)
				return

		# Post-resolution checks for conflicted merges: ensure fully resolved
		# (1) no conflict markers in files (worktree clean of markers)
		# (2) stage resolved files so index reflects resolution
		# (3) no unmerged entries remaining in the index
		if had_conflicts:
			# First ensure there are no conflict markers left
			if check_for_conflict_markers(out_dir):
				post_pr_comment(
					token,
					cfg.repo_full,
					cfg.pr_number,
					f"Conflict markers still present after resolution. Aborting. base={base_sha} head={head_sha} merge-base={merge_base}\n\nCodex stdout tail:\n{codex_stdout[-2000:]}",
				)
				return
			# Stage resolved files to mark conflicts as resolved in the index
			try:
				if conflicted_paths:
					git(["add", *sorted(conflicted_paths)], out_dir)
				else:
					git(["add", "-A"], out_dir)
			except subprocess.CalledProcessError as e:
				post_pr_comment(
					token,
					cfg.repo_full,
					cfg.pr_number,
					f"Failed to stage resolved files (exit={e.returncode}). Aborting. base={base_sha} head={head_sha} merge-base={merge_base}\n\nCodex stdout tail:\n{codex_stdout[-2000:]}",
				)
				return
			# Now verify no unmerged entries remain
			unmerged = git(["ls-files", "-u"], out_dir)
			if unmerged.strip():
				post_pr_comment(
					token,
					cfg.repo_full,
					cfg.pr_number,
					f"Unmerged entries remain after staging. Aborting. base={base_sha} head={head_sha} merge-base={merge_base}\n\nCodex stdout tail:\n{codex_stdout[-2000:]}",
				)
				return

		# Run optional hooks
		try:
			run_optional_hooks(out_dir)
		except subprocess.CalledProcessError as e:
			post_pr_comment(
				token,
				cfg.repo_full,
				cfg.pr_number,
				f"Post-resolution hook failed: {e}. Aborting. base={base_sha} head={head_sha} merge-base={merge_base}",
			)
			return

		# We always proceed to commit/push for clean merges (base..head has changes)
		# and for conflicted merges that are now fully resolved.

		# Commit the resolved changes on the current branch before creating new branch
		# This preserves the resolution so we can apply it to the new branch. We
		# create either (a) a merge commit for clean/FF paths or (b) a temporary
		# commit if Codex made edits. That commit is then cherry‑picked onto a
		# fresh branch forked from the base tip for publishing.
		git(["config", "user.name", "resbot"], out_dir)
		git(["config", "user.email", "resbot@noreply.local"], out_dir)
		# Ensure any in-repo `.resbot` telemetry directory from older runs is not
		# accidentally committed to the user's repository.
		shutil.rmtree(out_dir / ".resbot", ignore_errors=True)
		git(["add", "-A"], out_dir)
		# After Codex (and staging), ensure merge is resolvable:
		# - Work tree has no unmerged entries (checked earlier)
		# - No conflict markers remain (checked earlier)
		# Determine the resolution commit to publish.
		if had_conflicts:
			# Let Codex drive git. We only finalize based on the repo state it left.
			merge_head_path = out_dir / ".git" / "MERGE_HEAD"
			if merge_head_path.exists():
				# Codex kept the merge in progress and resolved files; finalize the merge commit.
				git(["commit", "--no-edit"], out_dir)
				resolution_commit_sha = git(["rev-parse", "HEAD"], out_dir)
			else:
				# If HEAD is already a merge commit (two parents), use it.
				parents_line = git(["rev-list", "-n", "1", "--parents", "HEAD"], out_dir)
				if len(parents_line.split()) >= 3:
					resolution_commit_sha = git(["rev-parse", "HEAD"], out_dir)
				else:
					# Finalize by committing the resolved worktree
					resolution_commit_msg = (
						f"resbot: resolution commit\n\n"
						f"base={base_sha}\nhead={head_sha}\nmerge-base={merge_base}\n"
					)
					try:
						git(["commit", "-m", resolution_commit_msg], out_dir)
					except subprocess.CalledProcessError:
						# Allow empty commit when the resolution matches one side exactly
						git(["commit", "--allow-empty", "-m", resolution_commit_msg], out_dir)
					resolution_commit_sha = git(["rev-parse", "HEAD"], out_dir)
		# For clean merges we do nothing (only act on conflicted PRs)
		# had_conflicts is always True past this point

		# Push resolution commit directly to the PR's head branch
		target_remote = "origin"
		if cfg.head_clone_url_opt and cfg.head_clone_url_opt != cfg.clone_url:
			# Fork PR: ensure 'fork' remote exists and points to the head repo
			try:
				git(["remote", "get-url", "fork"], out_dir)
			except subprocess.CalledProcessError:
				git(["remote", "add", "fork", head_clone_url_with_token], out_dir)
			target_remote = "fork"
		# Push HEAD to the head branch ref
		git(["push", target_remote, f"HEAD:refs/heads/{cfg.head_ref}", "--force-with-lease"], out_dir)

		comment = (
			f"base={base_sha} head={head_sha} merge-base={merge_base}\n"
			f"pushed resolution commit {resolution_commit_sha[:7]} to {target_remote}/{cfg.head_ref}"
		)
		post_pr_comment(token, cfg.repo_full, cfg.pr_number, comment)

	finally:
		# Cleanup workspace unless explicitly preserved via RESBOT_KEEP_WS=true.
		# When using a persistent volume for /ws, keeping it allows post-run inspection.
		try:
			keep_ws = os.environ.get("RESBOT_KEEP_WS", "").lower() == "true"
			if not keep_ws:
				shutil.rmtree("/ws", ignore_errors=True)
		except Exception:
			pass


if __name__ == "__main__":
	main()


