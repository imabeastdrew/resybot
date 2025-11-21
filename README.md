## Resybot

An Agent that resolves merge conflicts in pull requests using Codex. It only runs on requested conflicted PRs and pushes a resolution commit back to the PR head branch.

## Development

You can already use Resybot from CI by running the `resbot-runner` CLI inside
GitHub Actions (see the **GitHub Actions / CI integration** section in
[`docs/ops.md`](docs/ops.md)). The GitHub App + webhook server integration is
still evolving, but the core runner is stable enough for experimental CI usage.

## Installation

Resybot is not yet published to PyPI, nor the GitHub Marketplace. For now, install from source:

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
  - Comment `/resybot` on the PR, optionally followed by extra instructions, for example:
    - `/resybot merge function x into y and nothing else from PR head`
  - Resybot will reproduce the merge, attempt to resolve conflicts using Codex (taking your additional instructions into account), and push a resolution commit back to the PR head branch.

For Docker-based setups, CI images, and advanced configuration, see the docs below.

## Documentation

- **Ops: Deploy & Run**: architecture, Docker images, environment variables, and GitHub App/webhook setup ([`docs/ops.md`](docs/ops.md)).
- **Contributing**: how to set up a dev environment, propose changes, and open PRs ([`docs/contributing.md`](docs/contributing.md)).
- **Runbook**: how to rerun or abort jobs, troubleshoot common issues, and find artifacts ([`docs/runbook.md`](docs/runbook.md)).
- **Limits & Filters**: repository size/time limits, path filters, and exact-merge behavior ([`docs/limits.md`](docs/limits.md)).
- **License**: MIT License ([`LICENSE`](LICENSE)).


