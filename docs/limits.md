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
