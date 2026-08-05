$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Targets = @("data\interim", "data\enriched", "data\gold", "data\reports")
foreach ($relative in $Targets) {
    $target = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $relative))
    if (-not $target.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe target: $target" }
    Get-ChildItem -LiteralPath $target -Force | Remove-Item -Recurse -Force
}
Write-Host "Generated outputs removed; raw Synthea files preserved."

