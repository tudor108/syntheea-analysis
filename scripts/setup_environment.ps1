param([ValidateSet("3.11", "3.12", "3.13")][string]$PythonVersion = "3.11")
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) { & py "-$PythonVersion" -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Write-Host "Environment ready. Activate with: .\.venv\Scripts\Activate.ps1"
