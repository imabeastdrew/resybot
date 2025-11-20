# Ops: Deploy & Run

## Architecture

Resybot uses a git workflow and only acts on conflicted PRs:
- Server enqueues a run only when a pull request is currently conflicted (`mergeable_state == "dirty"`) **and** a user posts a manual `/resybot ...` issue comment on that PR
- Runner clones the PR repository directly to `/ws/out` as a real Git working directory
- Reproduces the merge by checking out the base commit and attempting to merge the head commit
- If no conflicts are detected, the runner exits immediately (no Codex, no commit/push)
- If conflicts exist, Codex runs with semantic in-place resolution instructions
- Post-resolution checks run, then resolve commit is created and pushed to the PR head

### High-level flow

- GitHub App receives repository events and forwards them to the Resybot server via webhooks.
- Server (`resbot-server`) validates the webhook signature using `GITHUB_WEBHOOK_SECRET`.
- For `issue_comment` events, the server enqueues a run when a user comments `/resybot ...` on a PR that is currently conflicted (`mergeable_state == "dirty"`). Any text after `/resybot` is forwarded to the runner and appended to the Codex merge prompt as additional instructions.
- Runner (`resbot-runner`) uses the GitHub App credentials to obtain an installation token, clones the repository into `/ws/out`, reproduces the merge between the base and head SHAs, invokes Codex to resolve conflicts in-place, runs optional hooks, and pushes a resolution commit back to the PR head branch.

## Components

- Server (`resbot.server.app`):
  - FastAPI application exposing `/webhook`.
  - Verifies signatures, inspects events, and spawns runner containers via the Docker SDK.
- Runner (`resbot.runner.main`):
  - Reads runtime configuration from environment variables set by the server.
  - Clones the PR repository, reproduces the merge, invokes Codex, validates the result, and pushes a resolution commit.

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
You can run the server either via Docker or directly from Python.

### Docker

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

- Set GitHub App webhook to `https://<host>/webhook`.

### Direct (without Docker)

For development you can run the FastAPI app directly:

```bash
export GITHUB_WEBHOOK_SECRET=...
export GITHUB_APP_ID=...
export GITHUB_PRIVATE_KEY='-----BEGIN PRIVATE KEY-----...'
export OPENAI_API_KEY=...

resbot-server
# or:
# uvicorn resbot.server.app.main:app --host 0.0.0.0 --port 8000
```

The runner normally runs inside its own Docker image, but you can also invoke it directly as long as the same environment is set:

```bash
resbot-runner
```

See the **Environment Variables** section below for a complete list of required values.

### Choosing runner image
- Override `RESBOT_RUNNER_IMAGE` to point at your published image, e.g.:
  - `RESBOT_RUNNER_IMAGE=ghcr.io/<org>/resbot-runner:latest`
  - or pin to a Codex tag: `RESBOT_RUNNER_IMAGE=ghcr.io/<org>/resbot-runner:rust-v0.50.0`

## Environment Variables

### Server environment

- `GITHUB_WEBHOOK_SECRET`: HMAC secret for webhook verification
- `GITHUB_APP_ID`: GitHub App ID
- `GITHUB_PRIVATE_KEY`: PEM contents for the app (server passes contents to runner)
- `RESBOT_RUNNER_IMAGE`: Docker image for the runner (e.g., `ghcr.io/<org>/resbot-runner:latest`)
- `RESBOT_MAX_REPO_MB`: soft limit for repository size processed (default `2000`)
- `RESBOT_MAX_EXEC_SECONDS`: max execution time for runner (default `600`)
- `CODEX_BIN`: Codex CLI binary (default `codex`)
- `CODEX_HOME`: Codex config dir (default `/app/codex/config`)
- `XDG_STATE_HOME`: Codex state dir (default `/app/codex/state`)
- `RESBOT_KEEP_WS`: optional (`true|false`) to keep `/ws` for inspection
- `OPENAI_API_KEY`: for Codex non-interactive login

### Runner environment (injected by the server)

- Core PR context:
  - `REPO_FULL`: `owner/repo` string
  - `CLONE_URL`: HTTPS Git clone URL of the base repo
  - `PR_NUMBER`: PR number
  - `BASE_REF` / `HEAD_REF`: branch names for base and head
  - `BASE_SHA` / `HEAD_SHA`: exact SHAs to merge
  - `HEAD_CLONE_URL`: clone URL of the head repo (for fork PRs)

- GitHub App credentials:
  - `INSTALLATION_ID`: GitHub App installation ID
  - `GITHUB_APP_ID`: GitHub App ID
  - `GITHUB_PRIVATE_KEY`: PEM contents used to generate an App JWT inside the runner

- Limits:
  - `RESBOT_MAX_REPO_MB`: soft limit for repository size (MB)
  - `RESBOT_MAX_EXEC_SECONDS`: max runtime (seconds)
  - `RESBOT_MAX_FILE_MB`: per-file size cap during copy/processing

- Codex configuration:
  - `CODEX_BIN`: Codex CLI executable
  - `CODEX_HOME`: Codex config directory (must be writable and persisted)
  - `XDG_STATE_HOME`: Codex state directory (history, logs, telemetry)
  - `OPENAI_API_KEY`: used for `codex login --with-api-key` when auth is required

- Workspace toggle:
  - `RESBOT_KEEP_WS`: when `true`, runner does not delete `/ws` on exit

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

- Events: `issue_comment` (you can leave `pull_request` subscribed in GitHub, but the server ignores it)

### Configuration

- Webhook URL: `https://<host>/webhook` (must match the GitHub App webhook URL)
- Secret: must match `GITHUB_WEBHOOK_SECRET` in the server environment

### Behavior

- `issue_comment`:
  - Comment `/resybot` (optionally followed by extra instructions) on a PR to enqueue a run.
  - Runner will exit immediately if the PR is clean by the time it executes (no Codex, no push).

## Logs
- Server logs via container output
- Runner reports via PR comment

## Volumes
Resybot uses named volumes so you can inspect workspaces and Codex state:

- `resbot_ws` → `/ws` (workspace; inspect merges and outputs under `/ws/out`)
- `codex_state` → `/app/codex/state` (Codex state/logs)
- `codex_config` → `/app/codex/config` (Codex config)

By default, the runner cleans up `/ws` at the end of a run unless `RESBOT_KEEP_WS=true`.

## Codex configuration
- `forced_login_method = "api"` to force API key auth in CI
- `sandbox_mode = "danger-full-access"` for containerized Linux
