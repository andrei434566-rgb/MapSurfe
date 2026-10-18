# MapSurfe GitHub sync

When the user explicitly asks to update this local project from GitHub, run .vscode/sync_from_github.ps1 from the repository root. It pulls origin/main only when the current branch is main and the working tree is clean.

If it stops because of local changes or a non-fast-forward update, report the message and stop. Never discard, stash, reset, clean, commit, or push local work as part of an update request.