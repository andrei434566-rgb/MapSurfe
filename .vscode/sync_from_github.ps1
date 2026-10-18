$ErrorActionPreference = 'Continue'

$repoRoot = & git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    Write-Error 'This task must be run inside the MapSurfe Git repository.'
    exit 1
}
Set-Location $repoRoot

$branch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) {
    Write-Error 'Could not determine the current Git branch.'
    exit 1
}
if ($branch -ne 'main') {
    Write-Host "Update stopped: current branch is '$branch'; switch to main first."
    exit 2
}

$changes = @(& git status --porcelain --untracked-files=normal)
if ($LASTEXITCODE -ne 0) {
    Write-Error 'Could not inspect the working tree.'
    exit 1
}
if ($changes.Count -gt 0) {
    Write-Host 'Update stopped because this folder has local changes:'
    $changes | ForEach-Object { Write-Host "  $_" }
    Write-Host 'Save or commit those changes before requesting a GitHub update.'
    exit 2
}

& git pull --ff-only origin main
$result = $LASTEXITCODE
if ($result -ne 0) {
    Write-Host 'Git could not fast-forward main. No local changes were discarded.'
    exit $result
}
Write-Host 'MapSurfe is up to date with origin/main.'