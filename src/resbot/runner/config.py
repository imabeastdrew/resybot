import os
from dataclasses import dataclass


@dataclass
class RunnerConfig:
	"""Runtime configuration passed in via environment variables.

	All fields map 1:1 to environment variables set by the server when spawning
	the runner.
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


