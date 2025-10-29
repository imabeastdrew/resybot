import os
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
	repo_full: str
	clone_url: str
	pr_number: int
	base_ref: str
	head_ref: str
	installation_id: int
	github_app_id: str
	github_private_key: str
	max_repo_mb: int
	max_exec_seconds: int
	max_file_mb: int


def read_env_config() -> RunnerConfig:
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
		installation_id=int(req("INSTALLATION_ID")),
		github_app_id=req("GITHUB_APP_ID"),
		github_private_key=req("GITHUB_PRIVATE_KEY"),
		max_repo_mb=int(os.environ.get("RESBOT_MAX_REPO_MB", "2000")),
		max_exec_seconds=int(os.environ.get("RESBOT_MAX_EXEC_SECONDS", "600")),
		max_file_mb=int(os.environ.get("RESBOT_MAX_FILE_MB", "10")),
	)


def create_app_jwt(app_id: str, private_key: str) -> str:
	from time import time
	claims = {"iat": int(time()) - 60, "exp": int(time()) + 540, "iss": app_id}
	if "BEGIN" in private_key and "\\n" not in private_key and "\n" not in private_key:
		private_key = private_key.replace("\\n", "\n")
	return jwt.encode(claims, private_key, algorithm="RS256")


def get_installation_token(app_id: str, private_key: str, installation_id: int) -> str:
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


def run(cmd: List[str], cwd: Path | None = None) -> str:
	res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True, capture_output=True, text=True)
	return res.stdout.strip()


def git(cmd: List[str], repo_dir: Path) -> str:
	return run(["git", *cmd], cwd=repo_dir)


def ensure_ws_dirs(root: Path) -> Dict[str, Path]:
	paths = {
		"root": root,
		"base": root / "base",
		"left": root / "left",
		"right": root / "right",
		"out": root / "out",
	}
	for p in paths.values():
		p.mkdir(parents=True, exist_ok=True)
	return paths


def compute_shas(repo_dir: Path, base_ref: str, head_ref: str) -> Tuple[str, str, str]:
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


def setup_worktrees(repo_dir: Path, ws_paths: Dict[str, Path], base_sha: str, head_sha: str, merge_base: str) -> None:
	git(["worktree", "add", "-f", str(ws_paths["base"]), merge_base], repo_dir)
	git(["worktree", "add", "-f", str(ws_paths["left"]), base_sha], repo_dir)
	git(["worktree", "add", "-f", str(ws_paths["right"]), head_sha], repo_dir)


def list_files_for_copy(left_dir: Path, max_file_mb: int) -> Tuple[int, int, List[Path]]:
	scanned = 0
	allowed: List[Path] = []
	excluded_dirs = {".git", "node_modules", "dist", "build"}
	max_bytes = max_file_mb * 1024 * 1024
	for root, dirs, files in os.walk(left_dir):
		# prune excluded dirs
		dirs[:] = [d for d in dirs if d not in excluded_dirs]
		for f in files:
			scanned += 1
			p = Path(root) / f
			try:
				size = p.stat().st_size
			except FileNotFoundError:
				continue
			if size <= max_bytes:
				allowed.append(p)
	filtered = scanned - len(allowed)
	return scanned, filtered, allowed


def rsync_left_to_out(left_dir: Path, out_dir: Path, max_file_mb: int) -> None:
	cmd = [
		"rsync",
		"-a",
		"--delete",
		"--exclude", ".git",
		"--exclude", "node_modules",
		"--exclude", "dist",
		"--exclude", "build",
		"--max-size", f"{max_file_mb}m",
		str(left_dir) + "/",
		str(out_dir) + "/",
	]
	run(cmd)


def post_pr_comment(token: str, repo_full: str, pr_number: int, body: str) -> None:
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
	cfg = read_env_config()
	token = get_installation_token(cfg.github_app_id, cfg.github_private_key, cfg.installation_id)

	owner, repo = cfg.repo_full.split("/", 1)
	clone_url_with_token = cfg.clone_url.replace("https://", f"https://x-access-token:{token}@")

	tmp_root = Path(tempfile.mkdtemp(prefix="resbot-"))
	repo_dir = tmp_root / "repo"
	repo_dir.mkdir(parents=True, exist_ok=True)

	try:
		# Clone and fetch refs
		run(["git", "clone", "--no-checkout", "--filter=blob:none", "--depth", "1", clone_url_with_token, str(repo_dir)])
		git(["fetch", "origin", f"+refs/heads/{cfg.base_ref}:refs/remotes/origin/{cfg.base_ref}", f"+refs/heads/{cfg.head_ref}:refs/remotes/origin/{cfg.head_ref}", "--depth", "400"], repo_dir)

		base_sha, head_sha, merge_base = compute_shas(repo_dir, cfg.base_ref, cfg.head_ref)

		ws = ensure_ws_dirs(Path("/ws"))
		setup_worktrees(repo_dir, ws, base_sha, head_sha, merge_base)

		scanned, filtered, allowed = list_files_for_copy(ws["left"], cfg.max_file_mb)
		rsync_left_to_out(ws["left"], ws["out"], cfg.max_file_mb)

		# Codex integration
		codex_bin = os.environ.get("CODEX_BIN", "codex")
		config_path = os.environ.get("CODEX_CONFIG_PATH", "codex/config/config.toml")
		try:
			# System prompt in TOML
			run([codex_bin, "run", "--config", config_path], cwd=Path("/app"))
		except subprocess.CalledProcessError as e:
			post_pr_comment(
				token,
				cfg.repo_full,
				cfg.pr_number,
				f"Codex failed (exit={e.returncode}). Aborting. base={base_sha} head={head_sha} merge-base={merge_base}",
			)
			return


		# Commit results on a new branch and open a PR
		branch_name = f"resbot/resolve-pr-{cfg.pr_number}-{head_sha[:7]}"
		git(["checkout", "-B", branch_name, base_sha], repo_dir)
		git(["config", "user.name", "resbot"], repo_dir)
		git(["config", "user.email", "resbot@noreply.local"], repo_dir)
		run([
			"rsync", "-a", "--delete",
			"--exclude", ".git",
			str(ws["out"]) + "/",
			str(repo_dir) + "/",
		])
		git(["add", "-A"], repo_dir)
		commit_msg = (
			f"resbot: resolve PR #{cfg.pr_number}\n\n"
			f"base={base_sha}\nhead={head_sha}\nmerge-base={merge_base}\n"
		)
		git(["commit", "-m", commit_msg], repo_dir)
		git(["push", "-u", "origin", branch_name], repo_dir)
		pr_title = f"resbot: resolve PR #{cfg.pr_number} ({head_sha[:7]})"
		pr_body = (
			f"Automated merge of PR #{cfg.pr_number} using resbot.\n\n"
			f"base={base_sha} head={head_sha} merge-base={merge_base}"
		)
		new_pr = create_pull_request(
			token=token,
			repo_full=cfg.repo_full,
			title=pr_title,
			head=branch_name,
			base=cfg.base_ref,
			body=pr_body,
		)
		new_pr_url = new_pr.get("html_url", "")

		comment = (
			f"base={base_sha} head={head_sha} merge-base={merge_base}\n"
			f"files scanned={scanned} filtered={filtered} copied={len(allowed)}\n"
			f"opened PR: {new_pr_url}"
		)
		post_pr_comment(token, cfg.repo_full, cfg.pr_number, comment)
	finally:
		# Cleanup
		try:
			shutil.rmtree("/ws", ignore_errors=True)
		except Exception:
			pass
		shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
	main()

