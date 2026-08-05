param([int]$CohortSize = 1000, [int]$Seed = 42, [string]$LogLevel = "INFO")
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    & $VenvPython -c "import pandas, pyarrow, duckdb, yaml, pydantic, typer" 2>$null
}
if ((Test-Path $VenvPython) -and $LASTEXITCODE -eq 0) {
    & $VenvPython -m prostate_journey.cli run-all --cohort-size $CohortSize --seed $Seed --log-level $LogLevel
} else {
    Write-Warning "The venv is incomplete; using installed compatible Python 3.13."
    & py -3.13 -m prostate_journey.cli run-all --cohort-size $CohortSize --seed $Seed --log-level $LogLevel
}
