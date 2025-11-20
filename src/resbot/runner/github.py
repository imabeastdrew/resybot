from dataclasses import dataclass
from time import time
from typing import Dict, Any

import jwt
import requests


def create_app_jwt(app_id: str, private_key: str) -> str:
	"""Create a short-lived JWT used to request an installation token."""
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


@dataclass
class GitHubClient:
	"""Thin wrapper over GitHub REST API scoped to a single repository."""

	token: str
	repo_full: str
	user_agent: str = "resbot-runner"

	@property
	def _headers(self) -> Dict[str, str]:
		return {
			"Authorization": f"token {self.token}",
			"Accept": "application/vnd.github+json",
			"User-Agent": self.user_agent,
		}

	@property
	def _owner_repo(self) -> tuple[str, str]:
		return self.repo_full.split("/", 1)

	def post_pr_comment(self, pr_number: int, body: str) -> None:
		"""Comment on a PR to report progress/failures back to users."""
		owner, repo = self._owner_repo
		url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
		resp = requests.post(url, json={"body": body}, headers=self._headers)
		resp.raise_for_status()

	def create_pull_request(
		self,
		title: str,
		head: str,
		base: str,
		body: str,
	) -> Dict[str, Any]:
		"""Open a PR from our resolution branch into the base branch."""
		owner, repo = self._owner_repo
		url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
		resp = requests.post(
			url,
			json={"title": title, "head": head, "base": base, "body": body},
			headers=self._headers,
		)
		resp.raise_for_status()
		return resp.json()


