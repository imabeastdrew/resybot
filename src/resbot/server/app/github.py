import base64
import json
import os
import time
from typing import Any, Dict

import jwt
import requests


def _load_private_key_from_env() -> str:
	key = os.environ.get("GITHUB_PRIVATE_KEY", "").strip()
	if not key:
		raise RuntimeError("GITHUB_PRIVATE_KEY must be set")
	return key
	

def create_app_jwt(app_id: str) -> str:
	private_key = _load_private_key_from_env()
	now = int(time.time())
	payload = {
		"iat": now - 60,
		"exp": now + 540,
		"iss": app_id,
	}
	return jwt.encode(payload, private_key, algorithm="RS256")


def get_installation_token(app_id: str, installation_id: int) -> str:
	app_jwt = create_app_jwt(app_id)
	url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
	resp = requests.post(url, headers={
		"Authorization": f"Bearer {app_jwt}",
		"Accept": "application/vnd.github+json",
		"User-Agent": "resbot-server",
	})
	resp.raise_for_status()
	return resp.json()["token"]


def get_pull_request(token: str, owner: str, repo: str, pr_number: int) -> Dict[str, Any]:
	url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
	resp = requests.get(url, headers={
		"Authorization": f"token {token}",
		"Accept": "application/vnd.github+json",
		"User-Agent": "resbot-server",
	})
	resp.raise_for_status()
	return resp.json()


