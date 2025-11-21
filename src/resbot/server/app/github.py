import os
import time
from dataclasses import dataclass
from typing import Any, Dict

import jwt  # type: ignore[import]
import requests


def _normalize_private_key(key: str) -> str:
	"""
	Handle PEM keys provided with literal "\\n" sequences instead of newlines.
	This matches the behavior in the runner so the same env value can be used.
	"""
	if "BEGIN" in key and "\\n" in key and "\n" not in key:
		return key.replace("\\n", "\n")
	return key


def load_private_key_from_env() -> str:
	key = os.environ.get("GITHUB_PRIVATE_KEY", "").strip()
	if not key:
		raise RuntimeError("GITHUB_PRIVATE_KEY must be set")
	return _normalize_private_key(key)
	

@dataclass
class GitHubAppClient:
	"""
	Small helper around GitHub App authentication and basic REST calls.

	This lives on the server side and is responsible for exchanging the App
	JWT for an installation token and reading PR metadata.
	"""

	app_id: str
	private_key: str
	user_agent: str = "resbot-server"
	api_base: str = "https://api.github.com"

	@classmethod
	def from_env(cls, app_id: str) -> "GitHubAppClient":
		"""Construct a client using GITHUB_PRIVATE_KEY from the environment."""
		return cls(app_id=app_id, private_key=load_private_key_from_env())

	def _app_jwt(self) -> str:
		now = int(time.time())
		payload = {
			"iat": now - 60,
			"exp": now + 540,
			"iss": self.app_id,
		}
		return jwt.encode(payload, self.private_key, algorithm="RS256")

	def _jwt_headers(self, app_jwt: str) -> Dict[str, str]:
		return {
			"Authorization": f"Bearer {app_jwt}",
			"Accept": "application/vnd.github+json",
			"User-Agent": self.user_agent,
		}

	def _token_headers(self, token: str) -> Dict[str, str]:
		return {
			"Authorization": f"token {token}",
			"Accept": "application/vnd.github+json",
			"User-Agent": self.user_agent,
		}

	def get_installation_token(self, installation_id: int) -> str:
		app_jwt = self._app_jwt()
		url = f"{self.api_base}/app/installations/{installation_id}/access_tokens"
		resp = requests.post(url, headers=self._jwt_headers(app_jwt))
		resp.raise_for_status()
		return resp.json()["token"]

	def get_pull_request(
		self, installation_id: int, owner: str, repo: str, pr_number: int
	) -> Dict[str, Any]:
		"""
		Fetch a pull request using an installation-scoped token for auth.
		"""
		token = self.get_installation_token(installation_id)
		url = f"{self.api_base}/repos/{owner}/{repo}/pulls/{pr_number}"
		resp = requests.get(url, headers=self._token_headers(token))
		resp.raise_for_status()
		return resp.json()

