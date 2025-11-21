import os
from typing import Dict


def build_runner_env(
	repo_full: str,
	clone_url: str,
	pr_number: int,
	base_ref: str,
	head_ref: str,
	base_sha: str,
	head_sha: str,
	head_clone_url: str,
	installation_id: int,
	app_id: str,
	pem_for_runner: str,
	user_prompt: str,
) -> Dict[str, str]:
	return {
		"REPO_FULL": repo_full,
		"CLONE_URL": clone_url,
		"PR_NUMBER": str(pr_number),
		"BASE_REF": base_ref,
		"HEAD_REF": head_ref,
		"BASE_SHA": base_sha,
		"HEAD_SHA": head_sha,
		"HEAD_CLONE_URL": head_clone_url,
		"INSTALLATION_ID": str(installation_id),
		"GITHUB_APP_ID": app_id,
		"GITHUB_PRIVATE_KEY": pem_for_runner,
		"CODEX_BIN": os.environ.get("CODEX_BIN", "codex"),
		"CODEX_HOME": os.environ.get("CODEX_HOME", "/app/codex/config"),
		"XDG_STATE_HOME": os.environ.get("XDG_STATE_HOME", "/app/codex/state"),
		"OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
		# Optional extra instructions from the issue comment (may be empty)
		"USER_PROMPT": user_prompt,
	}


def spawn_runner(envs: Dict[str, str]) -> None:
	# Docker SDK
	import docker

	client = docker.from_env()
	runner_image = os.environ.get("RESBOT_RUNNER_IMAGE", "resbot/runner:latest")
	# Mount persistent volumes so repo workspace and Codex state are inspectable
	volumes = {
		"resbot_ws": {"bind": "/ws", "mode": "rw"},
		"codex_state": {"bind": "/app/codex/state", "mode": "rw"},
		"codex_config": {"bind": "/app/codex/config", "mode": "rw"},
	}
	client.containers.run(
		image=runner_image,
		environment=envs,
		volumes=volumes,
		remove=True,
		detach=False,
	)


