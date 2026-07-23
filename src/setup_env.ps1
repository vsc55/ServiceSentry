# setup_env.ps1
[CmdletBinding()]
param(
    [string]$EnvName = ".venv",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Run($exe, [string[]]$cmdArgs) {
    Write-Host "→ $exe $($cmdArgs -join ' ')"
    & $exe @cmdArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Comando falló: $exe $($cmdArgs -join ' ') (exit $LASTEXITCODE)"
    }
}

# 1) Python exist
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "❌ Python is not installed or not in PATH."
    exit 1
}
Write-Host ("✔ Python {0} found." -f $python.Version)
Write-Host ("")


# 2) Delete venv if --Force is specified
if (Test-Path $EnvName) {
    if ($Force) {
        Write-Host "⚠ Deleting virtual environment '$EnvName' (due to --Force)..."
        Remove-Item -Recurse -Force $EnvName
    } else {
        Write-Host "⚠ Virtual environment '$EnvName' already exists. Use -Force to recreate."
        Write-Host ""
        exit 0
    }
}
Write-Host ""

# 3) Create venv
Write-Host "🛠 Creating virtual environment '$EnvName'..."
Run "python" @("-m","venv",$EnvName)
$py = Join-Path $EnvName "Scripts\python.exe"
Write-Host "✔ Virtual environment '$EnvName' created."
Write-Host ""

# Activate and upgrade pip
# .venv\Scripts\Activate.ps1

# 4) Harmonize pip / pip-tools
Write-Host "⬆ Updating pip and pip-tools..."
Run $py @("-m","pip","install","-U","pip")
Run $py @("-m","pip","install","-U","pip-tools")
Write-Host "✔ pip and pip-tools updated."
Write-Host ""

# 5) Install production dependencies from the LOCK (exact, hash-verified versions), so the
#    dev venv matches what Docker/CI deploy. requirements.txt (ranges) is only the source
#    the lock is compiled from — fall back to it if the lock is somehow missing.
if (Test-Path "requirements.lock") {
    Write-Host "📦 Installing pinned dependencies from requirements.lock..."
    Run $py @("-m","pip","install","-r","requirements.lock")
    Write-Host "✔ Dependencies installed (locked)."
} elseif (Test-Path "requirements.txt") {
    Write-Host "⚠ requirements.lock not found; installing ranges from requirements.txt."
    Run $py @("-m","pip","install","-r","requirements.txt")
    Write-Host "✔ Dependencies installed (unpinned)."
} else {
    Write-Host "⚠ No requirements.lock/txt found; nothing to install."
}
Write-Host ""

# 6) Install dependencies development
if (Test-Path "requirements-dev.txt") {
    Write-Host "📦 Installing dependencies from requirements-dev.txt..."
    Run $py @("-m","pip","install","-r","requirements-dev.txt")
    Write-Host "✔ Dependencies installed."
} else {
    Write-Host "⚠ No requirements-dev.txt found; nothing to install."
}
Write-Host ""

Write-Host "🎉 Virtual environment '$EnvName' ready." -Force
Write-Host ""

Write-Host "To activate it, run: `n`n    .\$EnvName\Scripts\Activate.ps1`n"
Write-Host ""