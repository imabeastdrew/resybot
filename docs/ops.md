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
- `CODEX_BIN`: Codex CLI binary (default `codex`)
- `CODEX_HOME`: Codex config dir (default `/app/codex/config`)
- `XDG_STATE_HOME`: Codex state dir (default `/app/codex/state`)
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

- Codex configuration:
  - `CODEX_BIN`: Codex CLI executable
  - `CODEX_HOME`: Codex config directory (must be writable and persisted)
  - `XDG_STATE_HOME`: Codex state directory (history, logs, telemetry)
  - `OPENAI_API_KEY`: used for `codex login --with-api-key` when auth is required

- Workspace toggle:
  - `RESBOT_KEEP_WS`: when `true`, runner does not delete `/ws` on exit

### Runner authentication modes

The runner supports two authentication modes:

- GitHub App mode (default):
  - Used when `GITHUB_TOKEN` is **not** set.
  - Requires: `INSTALLATION_ID`, `GITHUB_APP_ID`, and `GITHUB_PRIVATE_KEY`.
  - This is the mode used when the server enqueues a run in response to GitHub App webhooks.

- GitHub Actions / CI token mode:
  - Used when `GITHUB_TOKEN` is set in the environment.
  - The runner uses `GITHUB_TOKEN` directly for Git operations and REST API calls.
  - GitHub App credentials become optional (they are ignored for auth if `GITHUB_TOKEN` is present).
  - This mode is recommended when invoking `resbot-runner` directly from a GitHub Actions workflow.

### Post-Resolution Hooks (all default OFF)

Enable optional hooks that run after conflict resolution but before committing:

- `ENABLE_DEPS_INSTALL=true`: Install dependencies before running formatters/tests
- `INSTALL_CMD`: Command to install dependencies (e.g., `npm ci`, `pip install -r requirements.txt`)
- `ENABLE_FORMAT=true`: Run code formatting
- `FORMAT_CMD`: Command to format code (e.g., `prettier --write .`, `black .`)
- `ENABLE_TESTS=true`: Run test suite
- `TEST_CMD`: Command to run tests (e.g., `npm test`, `pytest`)

Example for a Node.js project:
```
ENABLE_DEPS_INSTALL=true
INSTALL_CMD=npm ci
ENABLE_FORMAT=true
FORMAT_CMD=prettier --write .
ENABLE_TESTS=true
TEST_CMD=npm test -- --ci
```

## Webhooks

- Events: `issue_comment` (you can leave `pull_request` and other events subscribed in GitHub, but the server ignores them)

### Configuration

- Webhook URL: `https://<host>/webhook` (must match the GitHub App webhook URL)
- Secret: must match `GITHUB_WEBHOOK_SECRET` in the server environment

### Behavior

- `issue_comment`:
  - Comment `/resybot` (optionally followed by extra instructions) on a PR to enqueue a run.
  - Comments on issues that are not pull requests are ignored (no runner is enqueued).
  - Runner will exit immediately if the PR is clean by the time it executes (no Codex, no push).

## Logs
- Server logs via container output
- Runner reports via PR comment

## Volumes
Resybot uses named volumes so you can inspect workspaces and Codex state:

- `resbot_ws` → `/ws` (workspace; inspect merges and outputs under `/ws/out`)
- `codex_state` → `/app/codex/state` (Codex state/logs)
- `codex_config` → `/app/codex/config` (Codex config)

The runner leaves `/ws` intact after each run so you can inspect workspaces; clean up the Docker volume when you no longer need it.

## GitHub Actions / CI integration

While the GitHub App + server remains the primary integration path, you can also
run the `resbot-runner` CLI directly from GitHub Actions. This is useful if you
prefer to avoid running the webhook server and instead drive Resybot entirely
from CI.

At a high level:

- Trigger a workflow (for example) on `issue_comment` or `workflow_dispatch`.
- Ensure the workflow only proceeds when:
  - the event is associated with a pull request, and
  - the comment body starts with `/resybot` (to match the server behavior).
- Populate the same environment variables the server would inject:
  - `REPO_FULL`, `CLONE_URL`, `PR_NUMBER`
  - `BASE_REF` / `HEAD_REF`
  - `BASE_SHA` / `HEAD_SHA`
  - `HEAD_CLONE_URL` (for fork PRs)
- Set `GITHUB_TOKEN` (provided by Actions) and Codex/OpenAI env vars.
- Install `resbot` and invoke `resbot-runner`.

Example (simplified) workflow snippet:

```yaml
name: Resybot (CI)

on:
  issue_comment:
    types: [created]

jobs:
  run-resybot:
    if: >
      github.event.issue.pull_request &&
      startsWith(github.event.comment.body, '/resybot')
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install resbot
        run: |
          pip install resbot  # or your published wheel / image

      - name: Prepare env and run resbot-runner
        env:
          REPO_FULL: ${{ github.repository }}
          CLONE_URL: ${{ github.event.repository.clone_url }}
          PR_NUMBER: ${{ github.event.issue.number }}
          # For issue_comment events you typically fetch the PR JSON using
          # the GitHub API to fill in BASE_REF/HEAD_REF/BASE_SHA/HEAD_SHA and
          # HEAD_CLONE_URL, mirroring what the server does.
          # Auth:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          # Codex / OpenAI:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          resbot-runner
```

The example above is intentionally high-level: in practice you will add a small
step that calls the GitHub REST API (e.g., via `curl` or `gh api`) to resolve
the PR's base/head refs and SHAs, then export them as environment variables
before running `resbot-runner`. The runner will then behave exactly as it does
when spawned by the server: clone the repository, reproduce the merge, and only
invoke Codex when real conflicts are present.

## Codex configuration
- `forced_login_method = "api"` to force API key auth in CI
- `sandbox_mode = "danger-full-access"` for containerized Linux
