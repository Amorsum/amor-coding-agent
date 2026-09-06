[CmdletBinding()]
param(
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$templateRoot = Join-Path $repositoryRoot "examples\calculator-repository"

if (-not $Destination) {
    $Destination = Join-Path $repositoryRoot "artifacts\demo-calculator"
}

$destinationPath = [System.IO.Path]::GetFullPath($Destination)
if (Test-Path $destinationPath) {
    throw "Destination already exists; choose a new path: $destinationPath"
}

New-Item -ItemType Directory -Path $destinationPath | Out-Null
Copy-Item -Path (Join-Path $templateRoot "*") -Destination $destinationPath -Recurse

git -C $destinationPath init --initial-branch=main
if ($LASTEXITCODE -ne 0) { throw "git init failed" }
git -C $destinationPath config user.name "AMOR Demo"
git -C $destinationPath config user.email "amor-demo@example.invalid"
git -C $destinationPath add .
git -C $destinationPath commit -m "chore: initialize calculator demo"
if ($LASTEXITCODE -ne 0) { throw "git commit failed" }

Write-Host "Demo repository created: $destinationPath"
Write-Host "Task and acceptance criteria: $destinationPath\AMOR-TASK.md"
