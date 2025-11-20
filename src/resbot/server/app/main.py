import hmac
import json
import os
import shlex
import subprocess
from hashlib import sha256
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Request

from .github import get_installation_token, get_pull_request, _load_private_key_from_env


app = FastAPI()


def _env(name: str, default: Optional[str] = None) -> str:
	value = os.environ.get(name, default)
	if value is None:
		raise RuntimeError(f"Missing required env: {name}")
	return value


def verify_signature(secret: str, body: bytes, signature_header: str) -> bool:
	expected = "sha256=" + hmac.new(secret.encode(), body, sha256).hexdigest()
	return hmac.compare_digest(expected, signature_header or "")


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


def _extract_repo_full(payload: Dict[str, Any]) -> str:
	repo = payload.get("repository", {})
	owner = repo.get("owner", {}).get("login")
	name = repo.get("name")
	return f"{owner}/{name}"


@app.post("/webhook")
async def webhook(
	request: Request,
	x_github_event: str = Header(None, alias="X-GitHub-Event"),
	x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
):
	body = await request.body()
	secret = _env("GITHUB_WEBHOOK_SECRET", "")
	if not secret or not verify_signature(secret, body, x_hub_signature_256 or ""):
		raise HTTPException(status_code=401, detail="Invalid signature")

	payload = json.loads(body.decode("utf-8"))
	installation = payload.get("installation", {})
	installation_id = installation.get("id")
	if not installation_id:
		raise HTTPException(status_code=400, detail="Missing installation id")

	repo_full = _extract_repo_full(payload)
	clone_url = payload.get("repository", {}).get("clone_url")
	app_id = _env("GITHUB_APP_ID")

	if x_github_event == "pull_request":
		# Automatic runs on conflicted PRs have been removed.
		# Resybot now only runs in response to manual /resybot issue comments.
		return {"status": "ignored", "reason": "auto_runs_disabled"}

	if x_github_event == "issue_comment":
		comment_body = payload.get("comment", {}).get("body", "") or ""
		comment = comment_body.strip()
		trigger = "/resybot"
		# Only respond to comments that start with the /resybot trigger
		if not comment.startswith(trigger):
			return {"status": "ignored"}
		# Everything after the trigger is treated as additional user instructions
		user_prompt = comment[len(trigger) :].strip()

		issue = payload.get("issue", {})
		pr_number = int(issue.get("number"))
		# Fetch PR details to resolve base/head
		installation_token = get_installation_token(app_id, int(installation_id))
		owner, repo = repo_full.split("/", 1)
		pr = get_pull_request(installation_token, owner, repo, pr_number)
		# Only act when the PR currently has conflicts
		mergeable_state = pr.get("mergeable_state")  # 'dirty' => conflicts present
		if mergeable_state != "dirty":
			return {"status": "skipped", "reason": "no_conflicts"}
		base_ref = pr.get("base", {}).get("ref")
		head_ref = pr.get("head", {}).get("ref")
		base_sha = pr.get("base", {}).get("sha") or ""
		head_sha = pr.get("head", {}).get("sha") or ""
		head_clone_url = pr.get("head", {}).get("repo", {}).get("clone_url") or ""
		pem_for_runner = _load_private_key_from_env()
		envs = {
			"REPO_FULL": repo_full,
			"CLONE_URL": clone_url or "",
			"PR_NUMBER": str(pr_number),
			"BASE_REF": base_ref or "",
			"HEAD_REF": head_ref or "",
			"BASE_SHA": base_sha,
			"HEAD_SHA": head_sha,
			"HEAD_CLONE_URL": head_clone_url,
			"INSTALLATION_ID": str(installation_id),
			"GITHUB_APP_ID": app_id,
			"GITHUB_PRIVATE_KEY": pem_for_runner,
			"RESBOT_MAX_REPO_MB": os.environ.get("RESBOT_MAX_REPO_MB", "2000"),
			"RESBOT_MAX_EXEC_SECONDS": os.environ.get("RESBOT_MAX_EXEC_SECONDS", "600"),
			"CODEX_BIN": os.environ.get("CODEX_BIN", "codex"),
			"CODEX_HOME": os.environ.get("CODEX_HOME", "/app/codex/config"),
			"XDG_STATE_HOME": os.environ.get("XDG_STATE_HOME", "/app/codex/state"),
			"RESBOT_KEEP_WS": os.environ.get("RESBOT_KEEP_WS", "false"),
			"OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
			# Optional extra instructions from the issue comment (may be empty)
			"USER_PROMPT": user_prompt,
		}
		spawn_runner(envs)
		return {"status": "queued"}

	raise HTTPException(status_code=200, detail="Unhandled event")


def run() -> None:
	import uvicorn
	uvicorn.run("resbot.server.app.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
	run()


