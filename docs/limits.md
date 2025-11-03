# Limits & Filters

## Size/time caps
- RESBOT_MAX_REPO_MB: soft limit for repository size processed
- RESBOT_MAX_EXEC_SECONDS: max execution time for runner
- RESBOT_MAX_FILE_MB: per-file size cap during copy

## Path filters (excluded)
- .git/
- node_modules/
- dist/
- build/

## Notes
- Conflict gating: Only runs when a PR is conflicted
  - Server checks GitHub PR `mergeable_state == "dirty"` and skips otherwise
  - Runner reproduces the merge and exits immediately if no conflicts are present (no Codex, no commit/push)
- Exact SHA materialization
  - Clone a real Git working directory at `/ws/out`
  - Ensure `BASE_SHA` and `HEAD_SHA` objects exist locally (fetch from origin/fork as needed)
  - Checkout base and attempt merge with the head to detect conflicts
- Single working tree
  - No auxiliary worktrees or snapshot directories; all edits happen in-place under `/ws/out`
