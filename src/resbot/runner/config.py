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
	# Optional free-form instructions provided via /resybot issue comments
	user_prompt: str = ""


def read_env_config() -> RunnerConfig:
	"""Load and validate required environment variables for this run.

	Supports two authentication modes:

	- GitHub App (default): when ``GITHUB_TOKEN`` is not set, the runner
	  requires ``INSTALLATION_ID``, ``GITHUB_APP_ID``, and
	  ``GITHUB_PRIVATE_KEY`` and will authenticate as a GitHub App
	  installation.
	- GitHub Actions / CI token (optional): when ``GITHUB_TOKEN`` is set, the
	  runner uses it directly for Git operations and REST calls, and GitHub
	  App credentials become optional.
	"""

	def req(name: str) -> str:
		val = os.environ.get(name)
		if not val:
			raise RuntimeError(f"Missing env: {name}")
		return val

	# When GITHUB_TOKEN is present we treat GitHub App credentials as optional
	# so the runner can be used directly from GitHub Actions without requiring
	# a full App installation.
	github_token = os.environ.get("GITHUB_TOKEN", "").strip()
	if github_token:
		installation_id = int(os.environ.get("INSTALLATION_ID", "0") or 0)
		github_app_id = os.environ.get("GITHUB_APP_ID", "")
		github_private_key = os.environ.get("GITHUB_PRIVATE_KEY", "")
	else:
		installation_id = int(req("INSTALLATION_ID"))
		github_app_id = req("GITHUB_APP_ID")
		github_private_key = req("GITHUB_PRIVATE_KEY")

	return RunnerConfig(
		repo_full=req("REPO_FULL"),
		clone_url=req("CLONE_URL"),
		pr_number=int(req("PR_NUMBER")),
		base_ref=req("BASE_REF"),
		head_ref=req("HEAD_REF"),
		base_sha_opt=os.environ.get("BASE_SHA", ""),
		head_sha_opt=os.environ.get("HEAD_SHA", ""),
		head_clone_url_opt=os.environ.get("HEAD_CLONE_URL", ""),
		installation_id=installation_id,
		github_app_id=github_app_id,
		github_private_key=github_private_key,
		user_prompt=os.environ.get("USER_PROMPT", "") or "",
	)


