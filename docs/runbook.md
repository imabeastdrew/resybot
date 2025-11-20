# Runbook: Rerun / Abort

## Rerun a job
- Comment on the PR: `/resybot` (optionally followed by extra instructions, for example `/resybot merge function x into y and nothing else from PR head`).
- Server enqueues a new runner container for that PR **only if** the PR is currently conflicted (`mergeable_state == "dirty"`). Any text after `/resybot` is forwarded to the runner and appended to the Codex merge prompt.
- If the PR has no conflicts (clean), the server skips the run and no new container is started.

## Abort a running job
- Stop the runner container on the host (e.g., `docker ps` then `docker stop <id>`)
- Jobs are idempotent; re-run by commenting again.

## Common issues
- 401 from webhook: verify `GITHUB_WEBHOOK_SECRET` matches the GitHub App setting.
- 403 from GitHub API: verify installation exists on target repo and app permissions.
- Clone failures: repo is large or rate limited; increase `RESBOT_MAX_EXEC_SECONDS` or retry.
- Nothing happens on comment: PR is clean; only conflicted PRs are processed. Verify PR `mergeable_state` is `dirty`.

## Where to find artifacts (local docker)
- Workspace: volume `resbot_ws` mounted at `/ws`
- Codex state/logs: volume `codex_state` mounted at `/app/codex/state`
- Codex config: volume `codex_config` mounted at `/app/codex/config`
