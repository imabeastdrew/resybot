import json

from fastapi import FastAPI, Header, HTTPException, Request

from .handlers import MissingInstallationIdError, handle_github_event
from .runner import spawn_runner
from .security import get_env, verify_signature


app = FastAPI()

@app.post("/webhook")
async def webhook(
	request: Request,
	x_github_event: str = Header(None, alias="X-GitHub-Event"),
	x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
):
	body = await request.body()
	secret = get_env("GITHUB_WEBHOOK_SECRET", "")
	if not secret or not verify_signature(secret, body, x_hub_signature_256 or ""):
		raise HTTPException(status_code=401, detail="Invalid signature")

	payload = json.loads(body.decode("utf-8"))
	try:
		response, envs = handle_github_event(x_github_event, payload)
	except MissingInstallationIdError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	if envs:
		spawn_runner(envs)
	return response


def run() -> None:
	import uvicorn
	uvicorn.run("resbot.server.app.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
	run()


