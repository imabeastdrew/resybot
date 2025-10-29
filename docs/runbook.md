# Runbook: Rerun / Abort

## Rerun a job
- Comment on the PR: `/resbot resolve`
- Server enqueues a new runner container for that PR.

## Abort a running job
- Stop the runner container on the host (e.g., `docker ps` then `docker stop <id>`)
- Jobs are idempotent; re-run by commenting again.

## Common issues
- 401 from webhook: verify `GITHUB_WEBHOOK_SECRET` matches the GitHub App setting.
- 403 from GitHub API: verify installation exists on target repo and app permissions.
- Clone failures: repo is large or rate limited; increase `RESBOT_MAX_EXEC_SECONDS` or retry.
