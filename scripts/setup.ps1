[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    Write-Host "==> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

Require-Command git
Require-Command python
Require-Command node
Require-Command npm
Require-Command docker

$nodeVersion = (& node --version).TrimStart("v")
$nodeMajor = [int]($nodeVersion.Split(".")[0])
if ($nodeMajor -lt 22) {
    throw "Node.js 22 or newer is required; found $nodeVersion"
}

Push-Location $repositoryRoot
try {
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        Invoke-Checked "Create Python virtual environment" { python -m venv .venv }
    }

    $venvPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
    Invoke-Checked "Upgrade pip" { & $venvPython -m pip install --upgrade pip }
    Invoke-Checked "Install AMOR and its test dependencies" { & $venvPython -m pip install -e ".[dev]" }

    Push-Location (Join-Path $repositoryRoot "web")
    try {
        Invoke-Checked "Install pinned frontend dependencies" { npm ci }
        Invoke-Checked "Build the local workbench" { npm run build }
    }
    finally {
        Pop-Location
    }

    Invoke-Checked "Check Docker Desktop" { docker info --format "{{.ServerVersion}}" }
    $imageReady = $false
    try {
        docker image inspect python:3.12-slim *> $null
        $imageReady = $LASTEXITCODE -eq 0
    }
    catch {
        $imageReady = $false
    }
    if (-not $imageReady) {
        Invoke-Checked "Pull the pinned sandbox image" { docker pull python:3.12-slim }
    }

    Write-Host ""
    Write-Host "AMOR is ready. Start it with:"
    Write-Host "  .venv\Scripts\amor web --artifacts artifacts"
}
finally {
    Pop-Location
}
