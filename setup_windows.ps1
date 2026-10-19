param(
    [switch]$SkipLaunch,
    [string]$Archive
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "MapSurfe / PaleoAtlas - Windows setup" -ForegroundColor Cyan

$venv = Join-Path $PSScriptRoot ".venv"
$pythonExe = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $candidates = @(
        @{ Name = "py"; Args = @("-3.11") },
        @{ Name = "py"; Args = @("-3.12") },
        @{ Name = "py"; Args = @("-3.13") },
        @{ Name = "py"; Args = @("-3") },
        @{ Name = "python"; Args = @() }
    )
    $found = $false
    $probe = 'import sys; print(sys.version.split()[0]); sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) and sys.maxsize > 2**32 else 2)'
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Name -ErrorAction SilentlyContinue)) { continue }
        $args = @($candidate.Args)
        try {
            & $candidate.Name @args -c $probe 2>$null
            if ($LASTEXITCODE -ne 0) { continue }
            Write-Host "Using Python: $($candidate.Name) $($args -join ' ')" -ForegroundColor Green
            & $candidate.Name @args -m venv $venv
            if ($LASTEXITCODE -ne 0) { throw "Could not create Python virtual environment." }
            $found = $true
            break
        }
        catch { continue }
    }
    if (-not $found) {
        throw "Python 3.10-3.13 x64 was not found. Install Python 3.11 x64 (with py launcher) and rerun."
    }
}
if (-not (Test-Path $pythonExe)) { throw "Virtual environment Python is missing." }

Write-Host ""
Write-Host "[1/3] Installing/updating dependencies..." -ForegroundColor Cyan
& $pythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $pythonExe -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

Write-Host ""
Write-Host "[2/3] Checking and installing map assets..." -ForegroundColor Cyan
$arguments = @((Join-Path $PSScriptRoot "tools\prepare_assets.py"))
if ($Archive) { $arguments += @("--archive", $Archive) }
& $pythonExe @arguments
if ($LASTEXITCODE -ne 0) { throw "Data preparation failed. You can manually download MapSurfe-source.zip from GitHub Releases and place it in this folder." }

Write-Host ""
Write-Host "[3/3] Checking modules..." -ForegroundColor Cyan
& $pythonExe -c "import PySide6, OpenGL, pygplates, cv2, netCDF4, numpy, pyproj; print('All modules imported successfully')"
if ($LASTEXITCODE -ne 0) { throw "A runtime dependency is broken." }

Write-Host ""
Write-Host "MapSurfe setup is ready." -ForegroundColor Green
if (-not $SkipLaunch) {
    Write-Host "Opening PaleoAtlas... (logs: paleoatlas-qt-error.log)" -ForegroundColor Cyan
    & $pythonExe (Join-Path $PSScriptRoot "paleoatlas_qt.pyw")
    if ($LASTEXITCODE -ne 0) { throw "App failed to start. Check paleoatlas-qt-error.log" }
}
