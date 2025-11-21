import hmac
import os
from hashlib import sha256
from typing import Any, Dict, Optional


def get_env(name: str, default: Optional[str] = None) -> str:
	value = os.environ.get(name, default)
	if value is None:
		raise RuntimeError(f"Missing required env: {name}")
	return value


def verify_signature(secret: str, body: bytes, signature_header: str) -> bool:
	expected = "sha256=" + hmac.new(secret.encode(), body, sha256).hexdigest()
	return hmac.compare_digest(expected, signature_header or "")


def extract_repo_full(payload: Dict[str, Any]) -> str:
	repo = payload.get("repository", {})
	owner = repo.get("owner", {}).get("login")
	name = repo.get("name")
	return f"{owner}/{name}"


