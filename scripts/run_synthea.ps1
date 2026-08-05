param(
    [int]$Population = 25000,
    [int]$Seed = 42,
    [string]$State = "Massachusetts"
)
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SyntheaRoot = Join-Path $ProjectRoot "external\synthea"
$RawTarget = Join-Path $ProjectRoot "data\raw\synthea"
if (-not (Get-Command java -ErrorAction SilentlyContinue)) { throw "Java is required. See docs/RUNBOOK.md." }
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Python launcher is required." }
$JavaCommand = Get-Command java
if (-not $env:JAVA_HOME -or -not (Test-Path (Join-Path $env:JAVA_HOME "bin\java.exe"))) {
    $env:JAVA_HOME = Split-Path (Split-Path $JavaCommand.Source -Parent) -Parent
    Write-Warning "JAVA_HOME was missing or invalid; using active JDK at $env:JAVA_HOME"
}
java -version
& py -3.11 --version
if (-not (Test-Path (Join-Path $SyntheaRoot "gradlew.bat"))) {
    New-Item -ItemType Directory -Path (Split-Path $SyntheaRoot) -Force | Out-Null
    git clone https://github.com/synthetichealth/synthea.git $SyntheaRoot
}
Set-Location $SyntheaRoot
& .\gradlew.bat build check
& .\run_synthea.bat -p $Population -s $Seed --exporter.csv.export=true --exporter.fhir.export=false $State
if ($LASTEXITCODE -ne 0) { throw "Synthea execution failed with exit code $LASTEXITCODE" }
New-Item -ItemType Directory -Path $RawTarget -Force | Out-Null
Copy-Item -Path (Join-Path $SyntheaRoot "output\csv\*.csv") -Destination $RawTarget -Force
Write-Host "Synthea CSV copied to $RawTarget"
