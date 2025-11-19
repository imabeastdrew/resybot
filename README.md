## Resybot

Resolve Bot (**resybot**) is an Agent that automatically resolves merge conflicts in pull requests by reproducing the exact Git merge in a runner container and using Codex to fix conflicts in-place. It only runs on conflicted PRs (`mergeable_state == "dirty"`) and pushes a resolution commit back to the PR head branch.

## Installation

Resybot is not yet published to PyPI. For now, install from source:

```bash
git clone https://github.com/<your-org>/resbot.git
cd resbot

python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install .
```

This installs the `resbot` Python package used to run Resybot and the CLI entrypoints:

- `resbot-server`
- `resbot-runner`

## Quickstart

- **Create a GitHub App**:
  - Grant permissions: Pull requests (Read/Write), Contents (Read/Write), Metadata (Read).
  - Set the webhook URL to `https://<your-host>/webhook` and choose a secret.

- **Export required environment variables** (for local development):

```bash
export GITHUB_WEBHOOK_SECRET=...
export GITHUB_APP_ID=...
export GITHUB_PRIVATE_KEY='-----BEGIN PRIVATE KEY-----...'
export OPENAI_API_KEY=...
```

- **Run the server**:

```bash
resbot-server
# or:
# uvicorn resbot.server.app.main:app --host 0.0.0.0 --port 8000
```

- **Trigger Resybot on a conflicted PR**:
  - Install the GitHub App on a repository.
  - Open a pull request that has merge conflicts with the base branch.
  - Comment `/resbot resolve` on the PR.
  - Resybot will reproduce the merge, attempt to resolve conflicts using Codex, and push a resolution commit back to the PR head branch.

For Docker-based setups, CI images, and advanced configuration, see the docs below.

## Documentation

- **Ops: Deploy & Run**: architecture, Docker images, environment variables, and GitHub App/webhook setup (`docs/ops.md`).
- **Contributing**: how to set up a dev environment, propose changes, and open PRs (`docs/contributing.md`).
- **Runbook**: how to rerun or abort jobs, troubleshoot common issues, and find artifacts (`docs/runbook.md`).
- **Limits & Filters**: repository size/time limits, path filters, and exact-merge behavior (`docs/limits.md`).
- **License**: MIT License (`LICENSE`).


