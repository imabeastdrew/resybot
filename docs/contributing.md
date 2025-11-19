## Contributing to Resybot

Contributions welcome! This document describes how to set up a development environment, make changes, and submit pull requests.

---

## Getting started

- **Fork and clone the repo**:

```bash
git clone https://github.com/<your-org>/resbot.git
cd resbot
```

- **Create a virtual environment** (Python 3.11+):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

The `-e` flag installs Resybot in editable mode, so code changes are picked up without reinstalling.

---

## Running the server and runner locally

- **Server**:

```bash
export GITHUB_WEBHOOK_SECRET=...
export GITHUB_APP_ID=...
export GITHUB_PRIVATE_KEY='-----BEGIN PRIVATE KEY-----...'
export OPENAI_API_KEY=...

resbot-server
```

- **Runner** (for debugging, normally run in Docker):

```bash
export REPO_FULL=owner/repo
export CLONE_URL=https://github.com/owner/repo.git
export PR_NUMBER=123
export BASE_REF=main
export HEAD_REF=feature-branch
export BASE_SHA=...
export HEAD_SHA=...
export INSTALLATION_ID=...
export GITHUB_APP_ID=...
export GITHUB_PRIVATE_KEY='-----BEGIN PRIVATE KEY-----...'
export OPENAI_API_KEY=...

resbot-runner
```

For a deeper overview of architecture, environment variables, and Docker-based workflows, see `docs/ops.md`.

---

## Code style and guidelines

- **Python version**: target Python 3.11+.
- **Style**:
  - Prefer clear, explicit code over clever one-liners.
  - Keep functions focused and small where reasonable.
  - Add or update docstrings for non-trivial functions and modules.
- **Configuration**:
  - Environment-driven behavior should be clearly documented in `docs/ops.md` or `docs/limits.md`.
  - Avoid hard-coding secrets or tokens; always rely on environment variables.

If you introduce new user-facing behavior (CLI flags, env vars, endpoints), please update the relevant docs under `docs/` and, if appropriate, the README.

---

## Tests and validation

Tests are yet to be added

At minimum, before opening a PR:

- Run the server locally and verify basic webhook flow in a test repository, or
- Run the runner against a known conflicted PR to ensure behavior is unchanged or improved.

---

## Submitting changes

1. **Open an issue** (optional but recommended) describing the bug or feature you want to work on.
2. **Create a feature branch**:

```bash
git checkout -b my-feature-branch
```

3. **Make your changes**, including updates to docs where needed.
4. **Commit with a clear message**:

```bash
git commit -am "Describe the change briefly"
```

5. **Push your branch** and open a pull request against the main repository:

```bash
git push origin my-feature-branch
```

6. In the PR description, include:
   - A short summary of the change.
   - Any relevant context or motivation.
   - Notes on testing (what you ran and the outcome).




