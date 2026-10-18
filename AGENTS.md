# MapSurfe agent instructions

When the user explicitly asks to update this local project from GitHub, run .vscode/sync_from_github.ps1 from this repository.

The script checks that the current branch is main and that the working tree is clean, then fast-forward pulls origin/main. If it stops because of local changes, report the listed changes and wait. Never discard, stash, reset, clean, commit, or push local work as part of a sync request.