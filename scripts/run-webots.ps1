[CmdletBinding()]
param(
    [ValidateSet("Auto", "Gpu", "Cpu")]
    [string]$GpuMode = "Auto",
    [string]$Scenario = "scenarios/smoke/unknown_stl_b.yaml",
    [string]$Output = "artifacts/local-webots",
    [int]$Seed = 1907
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$env:SAFESORT_GPU = $GpuMode.ToLowerInvariant()

Push-Location $repositoryRoot
try {
    python run_scenario.py run --scenario $Scenario --seed $Seed --output $Output
    if ($LASTEXITCODE -ne 0) {
        throw "SafeSort Webots run failed."
    }
}
finally {
    Pop-Location
}
