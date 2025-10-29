# Ops: Deploy & Run

## Prereqs
- GitHub App with permissions: Pull requests (RW), Contents (RW), Metadata (R)
- Secrets: GITHUB_APP_ID, GITHUB_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET
- Docker engine accessible to the server container

## Build Images
- make build-server
- make build-runner

## CI Images
- Workflows build and push images to GHCR.
- Runner: multi-arch; tags `latest` and the `CODEX_TAG` (e.g., `rust-v0.50.0`). Default: `ghcr.io/<org>/resbot-runner`.
- Server: multi-arch; tags `latest` and commit SHA. Default: `ghcr.io/<org>/resbot-server`.

## Push Images (optional)
- export REGISTRY=ghcr.io/your-org and optionally IMAGE_PREFIX
- make push-server
- make push-runner

## Run Server (local)
- Copy `.env.example` to `.env` and fill in values.
- Start server with `--env-file`:

```bash
docker run --rm -p 8000:8000 \
  --env-file ./.env \
  -e GITHUB_PRIVATE_KEY_FILE=/secrets/app.pem \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /absolute/path/to/app.pem:/secrets/app.pem:ro \
  ghcr.io/your-org/resbot-server:latest
```

- Set GitHub App webhook to https://<host>/webhook

### Choosing runner image
- Override `RESBOT_RUNNER_IMAGE` to point at your published image, e.g.:
  - `RESBOT_RUNNER_IMAGE=ghcr.io/<org>/resbot-runner:latest`
  - or pin to a Codex tag: `RESBOT_RUNNER_IMAGE=ghcr.io/<org>/resbot-runner:rust-v0.50.0`

## Webhooks
- Events: pull_request, issue_comment
- Trigger: comment "/resbot resolve" on a PR

## Logs
- Server logs via container output
- Runner reports via PR comment
