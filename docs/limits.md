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
- Shallow fetch depth: 400
- Worktrees used to materialize base/left/right snapshots
