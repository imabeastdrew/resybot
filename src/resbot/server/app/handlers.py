from typing import Any, Dict, Optional, Tuple

from .github import GitHubAppClient, load_private_key_from_env
from .runner import build_runner_env
from .security import extract_repo_full, get_env


class MissingInstallationIdError(Exception):
	"""Raised when a webhook payload does not contain an installation id."""


def handle_github_event(
	event: Optional[str], payload: Dict[str, Any]
) -> Tuple[Dict[str, Any], Optional[Dict[str, str]]]:
	installation = payload.get("installation", {})
	installation_id = installation.get("id")
	if not installation_id:
		raise MissingInstallationIdError("Missing installation id")

	if event == "pull_request":
		# Automatic runs on conflicted PRs have been removed.
		# Resybot now only runs in response to manual /resybot issue comments.
		return {"status": "ignored", "reason": "auto_runs_disabled"}, None

	if event == "issue_comment":
		repo_full = extract_repo_full(payload)
		clone_url = payload.get("repository", {}).get("clone_url") or ""
		app_id = get_env("GITHUB_APP_ID")
		return _handle_issue_comment_event(
			payload=payload,
			repo_full=repo_full,
			clone_url=clone_url,
			app_id=app_id,
			installation_id=int(installation_id),
		)

	# For unhandled events, respond with an explicit ignored status so the
	# caller can still return 200 without relying on HTTPException for control
	# flow.
	return {"status": "ignored", "reason": "unhandled_event"}, None


def _handle_issue_comment_event(
	payload: Dict[str, Any],
	repo_full: str,
	clone_url: str,
	app_id: str,
	installation_id: int,
) -> Tuple[Dict[str, Any], Optional[Dict[str, str]]]:
	comment_body = payload.get("comment", {}).get("body", "") or ""
	comment = comment_body.strip()
	trigger = "/resybot"
	# Only respond to comments that start with the /resybot trigger
	if not comment.startswith(trigger):
		return {"status": "ignored"}, None

	issue = payload.get("issue", {}) or {}
	# Only handle comments that are actually on pull requests. For comments on
	# plain issues, we treat the event as ignored so we don't attempt to fetch
	# a non-existent PR.
	if not issue.get("pull_request"):
		return {"status": "ignored", "reason": "not_pull_request_issue"}, None

	# Everything after the trigger is treated as additional user instructions
	user_prompt = comment[len(trigger) :].strip()

	pr_number = int(issue.get("number"))

	# Fetch PR details to resolve base/head
	github_app = GitHubAppClient.from_env(app_id)
	owner, repo = repo_full.split("/", 1)
	pr = github_app.get_pull_request(installation_id, owner, repo, pr_number)

	# Only act when the PR currently has conflicts
	mergeable_state = pr.get("mergeable_state")  # 'dirty' => conflicts present
	if mergeable_state != "dirty":
		return {"status": "skipped", "reason": "no_conflicts"}, None

	base_ref = pr.get("base", {}).get("ref") or ""
	head_ref = pr.get("head", {}).get("ref") or ""
	base_sha = pr.get("base", {}).get("sha") or ""
	head_sha = pr.get("head", {}).get("sha") or ""
	head_clone_url = pr.get("head", {}).get("repo", {}).get("clone_url") or ""
	pem_for_runner = load_private_key_from_env()

	envs = build_runner_env(
		repo_full=repo_full,
		clone_url=clone_url,
		pr_number=pr_number,
		base_ref=base_ref,
		head_ref=head_ref,
		base_sha=base_sha,
		head_sha=head_sha,
		head_clone_url=head_clone_url,
		installation_id=installation_id,
		app_id=app_id,
		pem_for_runner=pem_for_runner,
		user_prompt=user_prompt,
	)
	return {"status": "queued"}, envs


