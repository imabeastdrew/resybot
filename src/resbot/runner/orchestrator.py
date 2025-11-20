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


def run_orchestration(cfg: RunnerConfig) -> None:
	"""End-to-end flow: reproduce merge, run LLM, validate, publish resolution."""
	token = get_installation_token(cfg.github_app_id, cfg.github_private_key, cfg.installation_id)
	github_client = GitHubClient(token=token, repo_full=cfg.repo_full)

	clone_url_with_token = cfg.clone_url.replace(
		"https://", f"https://x-access-token:{token}@"
	)
	out_dir = Path("/ws/out")

	try:
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

		# LLM (Codex) integration - run in the conflicted repo (only when conflicts
		# existed).
		codex_bin = os.environ.get("CODEX_BIN", "codex")
		codex_home = os.environ.get("CODEX_HOME", "/app/codex/config")
		xdg_state_home = os.environ.get("XDG_STATE_HOME", "/app/codex/state")
		# Ensure the runner process exports XDG_STATE_HOME so telemetry reader sees it.
		os.environ["XDG_STATE_HOME"] = xdg_state_home
		openai_api_key = os.environ.get("OPENAI_API_KEY")

		# Gather conflict statistics for prompt construction.
		num_conflict_files = 0
		conflicted_paths_list: List[str] = []
		try:
			_conf_out = git(["diff", "--name-only", "--diff-filter=U"], out_dir)
			conflicted_paths_list = [p for p in _conf_out.splitlines() if p.strip()]
			num_conflict_files = len(conflicted_paths_list)
		except subprocess.CalledProcessError:
			num_conflict_files = 0

		num_conflicts = 0
		try:
			_marker_out = run(["grep", "-R", "-n", "-E", "^<<<<<<<"], cwd=out_dir)
			num_conflicts = len(
				[l for l in _marker_out.splitlines() if l.strip()]
			)
		except subprocess.CalledProcessError:
			num_conflicts = 0

		extra_instructions = (cfg.user_prompt or "").strip()
		merge_prompt = build_merge_prompt(
			num_conflicts, conflicted_paths_list, extra_instructions
		)

		# Ensure LLM client is authenticated before running exec.
		ok, error_msg, exit_code = ensure_codex_login(
			codex_bin=codex_bin,
			codex_home=codex_home,
			xdg_state_home=xdg_state_home,
			openai_api_key=openai_api_key,
		)
		if not ok:
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
			return

		# Before invoking the LLM, record the initially conflicted paths so we can
		# verify that its resolution actually touches those files later.
		conflicted_paths: Set[str] = set()
		try:
			_conf_out = git(["diff", "--name-only", "--diff-filter=U"], out_dir)
			conflicted_paths = {p for p in _conf_out.splitlines() if p}
		except subprocess.CalledProcessError:
			conflicted_paths = set()

		codex_stdout: str = ""
		try:
			codex_stdout = run_codex_exec(
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
			return

		# Post-resolution checks for conflicted merges: ensure fully resolved
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
			return

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
			return

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
			return

		# Run optional hooks
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
			return

		# We always proceed to commit/push for conflicted merges that are fully
		# resolved.
		git(["config", "user.name", "resbot"], out_dir)
		git(["config", "user.email", "resbot@noreply.local"], out_dir)
		# Ensure any in-repo `.resbot` telemetry directory from older runs is not
		# accidentally committed to the user's repository.
		shutil.rmtree(out_dir / ".resbot", ignore_errors=True)
		git(["add", "-A"], out_dir)

		# Determine the resolution commit to publish.
		merge_head_path = out_dir / ".git" / "MERGE_HEAD"
		if merge_head_path.exists():
			# LLM kept the merge in progress and resolved files; finalize the merge
			# commit.
			git(["commit", "--no-edit"], out_dir)
			resolution_commit_sha = git(["rev-parse", "HEAD"], out_dir)
		else:
			# If HEAD is already a merge commit (two parents), use it.
			parents_line = git(["rev-list", "-n", "1", "--parents", "HEAD"], out_dir)
			if len(parents_line.split()) >= 3:
				resolution_commit_sha = git(["rev-parse", "HEAD"], out_dir)
			else:
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
				resolution_commit_sha = git(["rev-parse", "HEAD"], out_dir)

		# Push resolution commit directly to the PR's head branch.
		target_remote = "origin"
		if cfg.head_clone_url_opt and cfg.head_clone_url_opt != cfg.clone_url:
			# Fork PR: ensure 'fork' remote exists and points to the head repo.
			try:
				git(["remote", "get-url", "fork"], out_dir)
			except subprocess.CalledProcessError:
				git(["remote", "add", "fork", head_clone_url_with_token], out_dir)
			target_remote = "fork"

		# Push HEAD to the head branch ref.
		git(
			[
				"push",
				target_remote,
				f"HEAD:refs/heads/{cfg.head_ref}",
				"--force-with-lease",
			],
			out_dir,
		)

		comment = (
			f"base={base_sha} head={head_sha} merge-base={merge_base}\n"
			f"pushed resolution commit {resolution_commit_sha[:7]} "
			f"to {target_remote}/{cfg.head_ref}"
		)
		github_client.post_pr_comment(cfg.pr_number, comment)

	finally:
		# Cleanup workspace unless explicitly preserved via RESBOT_KEEP_WS=true.
		# When using a persistent volume for /ws, keeping it allows post-run inspection.
		try:
			keep_ws = os.environ.get("RESBOT_KEEP_WS", "").lower() == "true"
			if not keep_ws:
				shutil.rmtree("/ws", ignore_errors=True)
		except Exception:
			pass


