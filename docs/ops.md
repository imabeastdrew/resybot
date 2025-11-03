# Ops: Deploy & Run

## Architecture

Resbot uses an exact-git workflow and only acts on conflicted PRs:
- Server enqueues a run only when the PR `mergeable_state` is `dirty` (conflicts)
- Runner clones the PR repository directly to `/ws/out` as a real Git working directory
- Reproduces the merge by checking out the base commit and attempting to merge the head commit
- If no conflicts are detected, the runner exits immediately (no Codex, no commit/push)
- If conflicts exist, Codex runs with semantic in-place resolution instructions
- Post-resolution checks run, then resolve commit is created and pushed to the PR head

## Prereqs
- GitHub App with permissions: Pull requests (RW), Contents (RW), Metadata (R)
- Secrets: GITHUB_APP_ID, GITHUB_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET
- Docker engine accessible to the server container

### Required environment variables
- `GITHUB_WEBHOOK_SECRET`: HMAC secret for webhook verification
- `GITHUB_APP_ID`: GitHub App ID
- `GITHUB_PRIVATE_KEY`: PEM contents for the app (server passes contents to runner)
- `OPENAI_API_KEY`: for Codex non-interactive login
- `CODEX_HOME`: Codex config dir (default `/app/codex/config`)
- `XDG_STATE_HOME`: Codex state dir (default `/app/codex/state`)
- `RESBOT_RUNNER_IMAGE`: optional override runner image
- `RESBOT_KEEP_WS`: optional (`true|false`) to keep `/ws` for inspection

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

## Environment Variables

### Post-Resolution Hooks (all default OFF)

Enable optional hooks that run after conflict resolution but before committing:

- `ENABLE_DEPS_INSTALL=true`: Install dependencies before running formatters/tests
- `INSTALL_CMD`: Command to install dependencies (e.g., `npm ci`, `pip install -r requirements.txt`)
- `ENABLE_FORMAT=true`: Run code formatting
- `FORMAT_CMD`: Command to format code (e.g., `prettier --write .`, `black .`)
- `ENABLE_TESTS=true`: Run test suite
- `TEST_CMD`: Command to run tests (e.g., `npm test`, `pytest`)
- `ENABLE_NETWORK=true`: Allow network access for dependency installation (required for `ENABLE_DEPS_INSTALL`)

Example for a Node.js project:
```
ENABLE_DEPS_INSTALL=true
INSTALL_CMD=npm ci
ENABLE_FORMAT=true
FORMAT_CMD=prettier --write .
ENABLE_TESTS=true
TEST_CMD=npm test -- --ci
ENABLE_NETWORK=true
```

## Webhooks
- Events: `pull_request`, `issue_comment`
- `pull_request`: server spawns a runner only if `mergeable_state == dirty`
- `issue_comment`: comment "/resbot resolve" on a PR to enqueue a run; runner will exit immediately if the PR is clean

## Logs
- Server logs via container output
- Runner reports via PR comment

## Volumes
- `resbot_ws` → `/ws` (workspace; inspect merges and outputs)
- `codex_state` → `/app/codex/state` (Codex state/logs)
- `codex_config` → `/app/codex/config` (Codex config)

## Codex configuration
- `forced_login_method = "api"` to force API key auth in CI
- `sandbox_mode = "danger-full-access"` for containerized Linux
