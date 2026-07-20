[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$SkipBuild,
    [ValidateSet("Auto", "Gpu", "Cpu")]
    [string]$GpuMode = "Auto",
    [ValidateRange(1, 65535)]
    [int]$Port = 4173,
    [ValidateRange(10, 1800)]
    [int]$TimeoutSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$url = "http://127.0.0.1:$Port/"
$env:SAFESORT_PORT = [string]$Port

Push-Location $repositoryRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker was not found. Install and start Docker Desktop."
    }

    $ErrorActionPreference = "Continue"
    & docker info 2> $null | Out-Null
    $dockerInfoExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($dockerInfoExitCode -ne 0) {
        throw "Docker Desktop is not responding. Start Docker Desktop and retry."
    }

    Write-Host "Starting SafeSort with Docker..."
    if (-not $SkipBuild) {
        $ErrorActionPreference = "Continue"
        & docker compose build demo
        $buildExitCode = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        if ($buildExitCode -ne 0) {
            throw "SafeSort container build failed."
        }
    }

    $gpuAvailable = $false
    if ($GpuMode -ne "Cpu") {
        $ErrorActionPreference = "Continue"
        & docker run --rm --network none --gpus all --entrypoint python deca123-sim:demo -c "import glob,os,sys; sys.exit(0 if os.path.exists('/dev/dxg') or glob.glob('/dev/nvidia*') else 1)" 2> $null | Out-Null
        $gpuProbeExitCode = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        $gpuAvailable = $gpuProbeExitCode -eq 0
        if ($GpuMode -eq "Gpu" -and -not $gpuAvailable) {
            throw "GPU mode was requested, but NVIDIA is not available inside Docker."
        }
    }

    $composeArguments = @("compose")
    if ($gpuAvailable) {
        $composeArguments += @("--file", "compose.yaml", "--file", "compose.gpu.yaml")
        Write-Host "Renderer: NVIDIA GPU passed to Docker." -ForegroundColor Green
    }
    else {
        Write-Host "Renderer: CPU fallback." -ForegroundColor Yellow
    }
    $composeArguments += @("up", "--detach", "demo")

    $ErrorActionPreference = "Continue"
    & docker @composeArguments
    $composeExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($composeExitCode -ne 0) {
        throw "SafeSort container startup failed."
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $ready = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 750
        }
    }

    if (-not $ready) {
        & docker compose ps
        & docker compose logs --tail 100 demo
        throw "The demo did not become ready within $TimeoutSeconds seconds."
    }

    Write-Host "SafeSort is ready: $url" -ForegroundColor Green

    if (-not $NoBrowser) {
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $url
        $startInfo.UseShellExecute = $true
        $opened = [System.Diagnostics.Process]::Start($startInfo)
        if ($null -eq $opened) {
            throw "The demo is running, but the browser did not open. Open $url manually."
        }
    }
}
finally {
    Pop-Location
}
