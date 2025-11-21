import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Set

from .config import RunnerConfig
from .github import GitHubClient, get_installation_token
from .git import check_for_conflict_markers, git, run, setup_conflicted_repo
from .hooks import run_optional_hooks
from .llms import build_merge_prompt, ensure_codex_login, run_codex_exec


def _prepare_llm_env() -> tuple[str, str, str, str | None]:
	"""Read and normalize LLM-related environment variables."""
	codex_bin = os.environ.get("CODEX_BIN", "codex")
	codex_home = os.environ.get("CODEX_HOME", "/app/codex/config")
	xdg_state_home = os.environ.get("XDG_STATE_HOME", "/app/codex/state")
	# Ensure the runner process exports XDG_STATE_HOME so telemetry reader sees it.
	os.environ["XDG_STATE_HOME"] = xdg_state_home
	openai_api_key = os.environ.get("OPENAI_API_KEY")
	return codex_bin, codex_home, xdg_state_home, openai_api_key


def _gather_conflict_stats_and_paths(out_dir: Path) -> tuple[List[str], Set[str], int]:
	"""Return (conflicted_paths_list, conflicted_paths_set, num_conflicts)."""
	conflicted_paths_list: List[str] = []
	conflicted_paths: Set[str] = set()
	try:
		_conf_out = git(["diff", "--name-only", "--diff-filter=U"], out_dir)
		conflicted_paths_list = [p for p in _conf_out.splitlines() if p.strip()]
		conflicted_paths = set(conflicted_paths_list)
	except subprocess.CalledProcessError:
		conflicted_paths_list = []
		conflicted_paths = set()

	num_conflicts = 0
	try:
		_marker_out = run(["grep", "-R", "-n", "-E", "^<<<<<<<"], cwd=out_dir)
		num_conflicts = len([l for l in _marker_out.splitlines() if l.strip()])
	except subprocess.CalledProcessError:
		num_conflicts = 0

	return conflicted_paths_list, conflicted_paths, num_conflicts


def _ensure_codex_login_or_report(
	github_client: GitHubClient,
	cfg: RunnerConfig,
	base_sha: str,
	head_sha: str,
	merge_base: str,
	codex_bin: str,
	codex_home: str,
	xdg_state_home: str,
	openai_api_key: str | None,
) -> bool:
	"""Ensure Codex login, posting PR comments on failure."""
	ok, error_msg, exit_code = ensure_codex_login(
		codex_bin=codex_bin,
		codex_home=codex_home,
		xdg_state_home=xdg_state_home,
		openai_api_key=openai_api_key,
	)
	if ok:
		return True

	if error_msg == "missing_api_key":
		github_client.post_pr_comment(
			cfg.pr_number,
			(
				f"Missing OPENAI_API_KEY. Cannot authenticate Codex. Aborting. "
				f"base={base_sha} head={head_sha} merge-base={merge_base}"
			),
		)
	else:
		github_client.post_pr_comment(
			cfg.pr_number,
			(
				f"Codex login failed (exit={exit_code}). Aborting. "
				f"base={base_sha} head={head_sha} merge-base={merge_base}\n\n"
				f"Error: {error_msg[:500]}"
			),
		)
	return False


def _run_codex_exec_or_report(
	github_client: GitHubClient,
	cfg: RunnerConfig,
	base_sha: str,
	head_sha: str,
	merge_base: str,
	codex_bin: str,
	merge_prompt: str,
	out_dir: Path,
	codex_home: str,
	xdg_state_home: str,
) -> str | None:
	"""Invoke Codex and post PR comments on failures."""
	try:
		return run_codex_exec(
			codex_bin=codex_bin,
			prompt=merge_prompt,
			out_dir=out_dir,
			codex_home=codex_home,
			xdg_state_home=xdg_state_home,
		)
	except subprocess.CalledProcessError as e:
		# Attach stderr tail for debugging.
		stderr_tail = (e.stderr or "")[-2000:] if hasattr(e, "stderr") else ""
		github_client.post_pr_comment(
			cfg.pr_number,
			(
				f"Codex failed (exit={e.returncode}). Aborting. "
				f"base={base_sha} head={head_sha} merge-base={merge_base}\n\n"
				f"Codex stderr tail:\n{stderr_tail}"
			),
		)
		return None


def _validate_and_stage_or_report(
	out_dir: Path,
	conflicted_paths: Set[str],
	github_client: GitHubClient,
	cfg: RunnerConfig,
	base_sha: str,
	head_sha: str,
	merge_base: str,
	codex_stdout: str,
) -> bool:
	"""Run post-resolution validation and staging, reporting failures via PR comments."""
	# Ensure fully resolved:
	# (1) no conflict markers in files (worktree clean of markers)
	# (2) stage resolved files so index reflects resolution
	# (3) no unmerged entries remaining in the index
	if check_for_conflict_markers(out_dir):
		github_client.post_pr_comment(
			cfg.pr_number,
			(
				f"Conflict markers still present after resolution. Aborting. "
				f"base={base_sha} head={head_sha} merge-base={merge_base}\n\n"
				f"Codex stdout tail:\n{codex_stdout[-2000:]}"
			),
		)
		return False

	# Stage resolved files to mark conflicts as resolved in the index.
	try:
		if conflicted_paths:
			git(["add", *sorted(conflicted_paths)], out_dir)
		else:
			git(["add", "-A"], out_dir)
	except subprocess.CalledProcessError as e:
		github_client.post_pr_comment(
			cfg.pr_number,
			(
				f"Failed to stage resolved files (exit={e.returncode}). Aborting. "
				f"base={base_sha} head={head_sha} merge-base={merge_base}\n\n"
				f"Codex stdout tail:\n{codex_stdout[-2000:]}"
			),
		)
		return False

	unmerged = git(["ls-files", "-u"], out_dir)
	if unmerged.strip():
		github_client.post_pr_comment(
			cfg.pr_number,
			(
				f"Unmerged entries remain after staging. Aborting. "
				f"base={base_sha} head={head_sha} merge-base={merge_base}\n\n"
				f"Codex stdout tail:\n{codex_stdout[-2000:]}"
			),
		)
		return False

	return True


def _run_post_resolution_hooks_or_report(
	out_dir: Path,
	github_client: GitHubClient,
	cfg: RunnerConfig,
	base_sha: str,
	head_sha: str,
	merge_base: str,
) -> bool:
	"""Run optional hooks, reporting failures via PR comments."""
	try:
		run_optional_hooks(out_dir)
	except subprocess.CalledProcessError as e:
		github_client.post_pr_comment(
			cfg.pr_number,
			(
				f"Post-resolution hook failed: {e}. Aborting. "
				f"base={base_sha} head={head_sha} merge-base={merge_base}"
			),
		)
		return False
	return True


def _finalize_resolution_commit(
	out_dir: Path,
	base_sha: str,
	head_sha: str,
	merge_base: str,
) -> str:
	"""Create or reuse a resolution commit and return its SHA."""
	# Ensure any in-repo `.resbot` telemetry directory from older runs is not
	# accidentally committed to the user's repository.
	shutil.rmtree(out_dir / ".resbot", ignore_errors=True)
	git(["add", "-A"], out_dir)

	merge_head_path = out_dir / ".git" / "MERGE_HEAD"
	if merge_head_path.exists():
		# LLM kept the merge in progress and resolved files; finalize the merge commit.
		git(["commit", "--no-edit"], out_dir)
		return git(["rev-parse", "HEAD"], out_dir)

	# If HEAD is already a merge commit (two parents), use it.
	parents_line = git(["rev-list", "-n", "1", "--parents", "HEAD"], out_dir)
	if len(parents_line.split()) >= 3:
		return git(["rev-parse", "HEAD"], out_dir)

	# Finalize by committing the resolved worktree.
	resolution_commit_msg = (
		f"resbot: resolution commit\n\n"
		f"base={base_sha}\nhead={head_sha}\nmerge-base={merge_base}\n"
	)
	try:
		git(["commit", "-m", resolution_commit_msg], out_dir)
	except subprocess.CalledProcessError:
		# Allow empty commit when the resolution matches one side exactly.
		git(
			["commit", "--allow-empty", "-m", resolution_commit_msg],
			out_dir,
		)
	return git(["rev-parse", "HEAD"], out_dir)


def _push_resolution(
	out_dir: Path,
	cfg: RunnerConfig,
	head_clone_url_with_token: str,
) -> str:
	"""Push the resolution commit to the appropriate remote and return its name."""
	target_remote = "origin"
	if cfg.head_clone_url_opt and cfg.head_clone_url_opt != cfg.clone_url:
		# Fork PR: ensure 'fork' remote exists and points to the head repo.
		try:
			git(["remote", "get-url", "fork"], out_dir)
		except subprocess.CalledProcessError:
			git(["remote", "add", "fork", head_clone_url_with_token], out_dir)
		target_remote = "fork"

	git(
		[
			"push",
			target_remote,
			f"HEAD:refs/heads/{cfg.head_ref}",
			"--force-with-lease",
		],
		out_dir,
	)
	return target_remote


def _post_success_comment(
	github_client: GitHubClient,
	cfg: RunnerConfig,
	base_sha: str,
	head_sha: str,
	merge_base: str,
	resolution_commit_sha: str,
	target_remote: str,
) -> None:
	"""Post a final success comment back to the PR."""
	comment = (
		f"base={base_sha} head={head_sha} merge-base={merge_base}\n"
		f"pushed resolution commit {resolution_commit_sha[:7]} "
		f"to {target_remote}/{cfg.head_ref}"
	)
	github_client.post_pr_comment(cfg.pr_number, comment)


def _resolve_github_token(cfg: RunnerConfig) -> str:
	"""Resolve the GitHub token used for API and Git operations.

	Preference order:
	- When GITHUB_TOKEN is set, use it directly (Actions/CI mode).
	- Otherwise, fall back to a GitHub App installation token derived from
	  GITHUB_APP_ID / GITHUB_PRIVATE_KEY / INSTALLATION_ID.
	"""
	direct_token = os.environ.get("GITHUB_TOKEN", "").strip()
	if direct_token:
		return direct_token

	return get_installation_token(
		cfg.github_app_id,
		cfg.github_private_key,
		cfg.installation_id,
	)


def run_orchestration(cfg: RunnerConfig) -> None:
	"""End-to-end flow: reproduce merge, run LLM, validate, publish resolution."""
	token = _resolve_github_token(cfg)
	github_client = GitHubClient(token=token, repo_full=cfg.repo_full)

	clone_url_with_token = cfg.clone_url.replace(
		"https://", f"https://x-access-token:{token}@"
	)
	out_dir = Path("/ws/out")

	# Clone repo directly to /ws/out and set up merge state using exact SHAs when
	# provided.
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

	# Only act when there are conflicts; otherwise exit immediately.
	if not had_conflicts:
		return

	# LLM (Codex) integration - run in the conflicted repo (only when conflicts existed).
	codex_bin, codex_home, xdg_state_home, openai_api_key = _prepare_llm_env()

	# Gather conflict statistics for prompt construction and record the initially
	# conflicted paths so we can verify resolution later.
	conflicted_paths_list, conflicted_paths, num_conflicts = _gather_conflict_stats_and_paths(
		out_dir
	)

	extra_instructions = (cfg.user_prompt or "").strip()
	merge_prompt = build_merge_prompt(
		num_conflicts, conflicted_paths_list, extra_instructions
	)

	# Ensure LLM client is authenticated before running exec.
	if not _ensure_codex_login_or_report(
		github_client,
		cfg,
		base_sha,
		head_sha,
		merge_base,
		codex_bin,
		codex_home,
		xdg_state_home,
		openai_api_key,
	):
		return

	codex_stdout = _run_codex_exec_or_report(
		github_client,
		cfg,
		base_sha,
		head_sha,
		merge_base,
		codex_bin,
		merge_prompt,
		out_dir,
		codex_home,
		xdg_state_home,
	)
	if codex_stdout is None:
		return

	if not _validate_and_stage_or_report(
		out_dir,
		conflicted_paths,
		github_client,
		cfg,
		base_sha,
		head_sha,
		merge_base,
		codex_stdout,
	):
		return

	if not _run_post_resolution_hooks_or_report(
		out_dir,
		github_client,
		cfg,
		base_sha,
		head_sha,
		merge_base,
	):
		return

	resolution_commit_sha = _finalize_resolution_commit(
		out_dir,
		base_sha,
		head_sha,
		merge_base,
	)

	target_remote = _push_resolution(
		out_dir,
		cfg,
		head_clone_url_with_token,
	)

	_post_success_comment(
		github_client,
		cfg,
		base_sha,
		head_sha,
		merge_base,
		resolution_commit_sha,
		target_remote,
	)

